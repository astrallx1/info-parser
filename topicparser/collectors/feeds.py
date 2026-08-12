"""Official feeds — the third source, beside GitHub and X.

GitHub finds repos and X finds what people SAY about a release. Neither finds the
release ITSELF at the moment it is published. The lab's own blog does, and so does its
YouTube channel — and both speak the same format, so one collector covers both:

    https://blog.google/technology/ai/rss/                     (RSS)
    https://openai.com/news/rss.xml                            (RSS)
    https://deepmind.google/blog/rss.xml                       (RSS)
    https://huggingface.co/blog/feed.xml                       (Atom)
    https://www.youtube.com/feeds/videos.xml?channel_id=<id>   (Atom, no API key)

This is the first-party channel: a two-hour course from Google is here the second it
goes up, hours before an aggregator rewrites it into a thread. That matters because
the scoring rules judge WHOSE fact it is — somebody's retelling of a lab's release is
down-ranked, the lab's own release is not.

Stdlib XML on purpose. RSS 2.0 and Atom are the only two shapes worth handling,
`feedparser` would be a dependency for a hundred lines, and every parse here is
defensive: a malformed feed skips that source, it never takes the run down.
"""
import html
import re
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import requests

from topicparser import i18n
from topicparser.models import Signal

# Per feed; a busy blog must not crowd out the other sources. Declared here, in
# `.env.example` and in `main.build_collectors` as `FEED_MAX_ITEMS` — three copies, all
# pinned by `test_feed_ceiling.py`, because a number that lives in one file and is read
# by nobody cannot be tuned. Whether it BINDS is only visible through `collect`'s stats
# below: the cap applies before the freshness filter, so the run log used to show a
# truncated feed and a quiet one as the same number.
DEFAULT_LIMIT = 25
DESCRIPTION_CAP = 600

_TAG = re.compile(r"<[^>]+>")
_ENTITY_DECL = re.compile(rb"<!ENTITY", re.I)
# What a single feed may send. A timeout bounds how LONG a source may take to answer,
# not how MUCH it may send, and the whole body went into memory before anything looked
# at it.
MAX_FEED_BYTES = 5 * 1024 * 1024
_WS = re.compile(r"\s+")


def _text(raw: str) -> str:
    """Feed summaries are HTML — often a whole styled paragraph. The scorer reads
    plain text and the card renders it verbatim, so strip the markup here.

    ORDER MATTERS: tags come off FIRST, entities are decoded SECOND. The other way
    round turns escaped prose into markup and then eats it — `_TAG` is `<[^>]+>`, so
    once `5 &lt; 10 and x &gt; y` is unescaped it matches "< 10 and x >" and the
    sentence reads "5 y". A triple-escaped `&lt;p&gt;` therefore survives as literal
    text; that is the deliberate side of the trade, and a second stripping pass would
    buy it back at the price of every sentence containing a < or a >."""
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", raw or ""))).strip()


def _local(tag: str) -> str:
    """`{http://www.w3.org/2005/Atom}entry` -> `entry`. Feeds disagree about
    namespaces and half of them declare more than one, so match on the local name."""
    return tag.rsplit("}", 1)[-1]


def _find(node, name: str):
    for child in node.iter():
        if _local(child.tag) == name:
            return child
    return None


def _entry_link(node) -> str:
    """RSS puts the URL in the element's TEXT, Atom in an `href` attribute."""
    for child in node.iter():
        if _local(child.tag) != "link":
            continue
        href = (child.get("href") or "").strip()
        rel = child.get("rel")
        if href and rel in (None, "alternate"):
            return href
        if (child.text or "").strip():
            return child.text.strip()
    return ""


def _entry_date(node) -> str:
    """ISO, whatever went in. RSS dates are RFC 822 and Atom's are already ISO;
    `prefilter` parses ISO, and a date it cannot read keeps the signal forever."""
    for name in ("published", "updated", "pubDate", "date"):
        el = _find(node, name)
        raw = (el.text or "").strip() if el is not None else ""
        if not raw:
            continue
        try:
            return parsedate_to_datetime(raw).isoformat()
        except (TypeError, ValueError):
            pass
        try:
            from datetime import datetime
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).isoformat()
        except ValueError:
            continue
    return ""


def _is_media(el) -> bool:
    """`<content medium="image" url="..."/>` is a thumbnail, not a summary. DeepMind's
    feed carries one on every item, and without this its URL would be read as the
    description and shipped to the scorer as the signal's text."""
    return (el.get("medium") not in (None, "text")
            or (el.get("type") or "text").split("/")[0] not in ("text", "html", "xhtml"))


def _entry_description(node) -> str:
    for name in ("description", "summary", "content", "media:description"):
        el = _find(node, name.split(":")[-1])
        if el is None or _is_media(el):
            continue
        # `.text` is only what precedes the first CHILD element, and an Atom summary
        # with type="xhtml" keeps everything in children — so those entries reached
        # the scorer with no text at all and were judged on their title alone.
        raw = "".join(el.itertext())
        if raw.strip():
            return _text(raw)[:DESCRIPTION_CAP]
    return ""


def _has_entity_decls(xml) -> bool:
    """Does the prolog DECLARE entities? That, not the DOCTYPE, is the bomb.

    Four levels of nested entities already expand to a 10 000-character title here;
    two more make it tens of megabytes. Refusing every `<!DOCTYPE` instead would break
    live feeds that legitimately carry one, so the declaration is the exact condition.
    """
    head = xml if isinstance(xml, bytes) else (xml or "").encode("utf-8", "ignore")
    head = head[:65536]
    i = head.find(b"<!DOCTYPE")
    if i < 0:
        return False
    end = head.find(b">", i)
    sub = head.find(b"[", i)
    if 0 <= sub < (end if end >= 0 else len(head)):
        end = head.find(b"]>", sub)
    return bool(_ENTITY_DECL.search(head[i:end if end >= 0 else len(head)]))


def parse_feed(xml, profile: str, limit: int = DEFAULT_LIMIT) -> list[Signal]:
    """RSS `<item>` or Atom `<entry>` -> Signals. Never raises: rubbish yields [].

    Give it BYTES where you can. `requests` guesses the encoding from the HTTP header
    and falls back to ISO-8859-1 for `text/*` when none is declared, which is how
    Google's feed arrived as "Weâre launching" — a UTF-8 apostrophe read as latin-1.
    ElementTree reads the `<?xml encoding=...?>` declaration off the raw bytes and
    gets it right.
    """
    if _has_entity_decls(xml):
        return []
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return []

    out = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        title_el = _find(node, "title")
        title = _text(title_el.text if title_el is not None else "")
        url = _entry_link(node)
        if not title or not url:
            continue          # every card has an Open button; a linkless entry is a dead end
        out.append(Signal.make(source="feed", title=title,
                               description=_entry_description(node),
                               url=url, date=_entry_date(node), profile=profile))
        if len(out) >= limit:
            break
    return out


class FeedCollector:
    source = "feed"

    def __init__(self, limit: int = DEFAULT_LIMIT, timeout: float = 20):
        self.limit = limit
        self.timeout = timeout
        # What each URL yielded, mirroring `XCollector.stats` / `x_sources`. Read by
        # `pipeline` into the debug log.
        self.stats: list[dict] = []

    def _fetch(self, url: str) -> bytes:
        """The body, capped. A seam so the collector is testable without network."""
        with requests.get(url, timeout=self.timeout, stream=True,
                          headers={"User-Agent": "Mozilla/5.0 (Info Parser)"}) as r:
            r.raise_for_status()
            chunks, total = [], 0
            for chunk in r.iter_content(65536):
                total += len(chunk)
                if total > MAX_FEED_BYTES:
                    # raised inside the caller's try, so this reads as one more skipped
                    # source in the warning banner and the run continues
                    raise ValueError(f"feed over {MAX_FEED_BYTES // 1024 // 1024} MB")
                chunks.append(chunk)
            return b"".join(chunks)

    def collect(self, profile_name: str, profile_cfg: dict) -> list[Signal]:
        """Two lists, one loop. `urls` are FIRST-PARTY sources — a lab's own blog or
        channel, which `_feedgate.txt` is written to judge. `interviews` are podcasts
        and shows that talk TO people; the gate's question does not apply to them, so
        the signals carry `first_party=False` and it never sees them."""
        cfg = profile_cfg.get("feeds") or {}
        feeds = [(u, True) for u in (cfg.get("urls") or [])] \
              + [(u, False) for u in (cfg.get("interviews") or [])]
        if not feeds:
            return []
        cancel = getattr(self, "cancel_event", None)
        warn = getattr(self, "warn", None)
        out: dict[str, Signal] = {}
        # One collector serves every profile in a run, so this is per CALL, not
        # cumulative — the second profile would otherwise inherit the first one's rows.
        self.stats = []
        for url, first_party in feeds:
            if cancel is not None and cancel.is_set():
                break
            # `items` is counted BEFORE the freshness filter, which is the only place
            # the ceiling is observable at all: a feed truncated at the cap and then
            # aged down reads exactly like a feed that published that few. A row is
            # written even for a feed that FAILED — that is precisely when the number
            # is worth having, the same rule `x_sources` follows.
            got = 0
            try:
                items = parse_feed(self._fetch(url), profile_name, self.limit)
                got = len(items)
                for sig in items:
                    if not first_party:
                        sig.first_party = False
                    out.setdefault(sig.url, sig)
            except Exception as e:
                if warn is not None:
                    warn(i18n.t("warn.feed_skipped", url=url, error=e))
            self.stats.append({"url": url, "items": got,
                               "capped": got >= self.limit,
                               "first_party": first_party})
        return list(out.values())
