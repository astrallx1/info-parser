"""The third source: official feeds.

GitHub finds repos and X finds what people SAY about a release. Neither finds the
release itself at the moment it is published — the lab's own blog and its YouTube
channel do, and both speak the same format. A free two-hour course from Google is in
its channel feed the second it goes up, hours before an aggregator rewrites it into a
thread, and a first-party fact is exactly the raw material the owner writes his own
angle on top of.

Stdlib XML on purpose: RSS and Atom are the two shapes that matter, `feedparser` is a
dependency for something a hundred lines can do, and a malformed feed must degrade to
"that one source is skipped" rather than take a 20-minute run down.
"""
import pytest

from topicparser.collectors.feeds import FeedCollector, parse_feed

RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Google AI</title>
  <item>
    <title>A free 2-hour course on agent graphs</title>
    <link>https://blog.google/technology/ai/agent-graphs/</link>
    <description>&lt;p&gt;Build your first agent, then &lt;b&gt;wire&lt;/b&gt; them into graphs.&lt;/p&gt;</description>
    <pubDate>Mon, 10 Aug 2026 09:30:00 +0000</pubDate>
  </item>
  <item>
    <title>Older post</title>
    <link>https://blog.google/technology/ai/older/</link>
    <description>Something else.</description>
    <pubDate>Tue, 04 Aug 2026 12:00:00 +0000</pubDate>
  </item>
</channel></rss>"""

# what youtube.com/feeds/videos.xml actually returns
ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">
  <title>DeepLearningAI</title>
  <entry>
    <title>Building Agent Graphs, Full Course</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=abc123"/>
    <published>2026-08-10T09:30:00+00:00</published>
    <media:group><media:description>Two hours, from prompt to multi-agent system.</media:description></media:group>
  </entry>
</feed>"""


def test_an_rss_item_becomes_a_signal():
    sigs = parse_feed(RSS, profile="AI")
    assert [s.title for s in sigs] == ["A free 2-hour course on agent graphs", "Older post"]
    first = sigs[0]
    assert first.source == "feed"
    assert first.url == "https://blog.google/technology/ai/agent-graphs/"
    assert first.date.startswith("2026-08-10T09:30:00")
    assert first.profile == "AI"


def test_html_is_stripped_from_the_description():
    """The scorer reads plain text, and the .md and the card render it verbatim."""
    body = parse_feed(RSS, profile="AI")[0].description
    assert "<" not in body and ">" not in body
    assert body == "Build your first agent, then wire them into graphs."


def test_an_atom_entry_becomes_a_signal():
    """YouTube channel feeds are Atom: the link is an attribute, not text, and the
    description hides in media:group."""
    sigs = parse_feed(ATOM, profile="AI")
    assert len(sigs) == 1
    assert sigs[0].title == "Building Agent Graphs, Full Course"
    assert sigs[0].url == "https://www.youtube.com/watch?v=abc123"
    assert sigs[0].date.startswith("2026-08-10T09:30:00")
    assert "multi-agent" in sigs[0].description


def test_dates_come_out_as_iso_whatever_went_in():
    """RSS dates are RFC 822 and Atom's are ISO. `prefilter` parses ISO, and a date it
    cannot read means the signal is kept forever as 'unknown'."""
    from datetime import datetime
    for sig in parse_feed(RSS, profile="AI") + parse_feed(ATOM, profile="AI"):
        datetime.fromisoformat(sig.date)          # raises if it is not ISO


def test_an_entry_with_no_link_is_dropped():
    """Every card has an Open button and the .md writes the URL — a signal with no
    link is a dead end."""
    feed = RSS.replace("<link>https://blog.google/technology/ai/agent-graphs/</link>", "")
    assert [s.title for s in parse_feed(feed, profile="AI")] == ["Older post"]


def test_rubbish_yields_nothing_instead_of_raising():
    assert parse_feed("<html>not a feed at all", profile="AI") == []
    assert parse_feed("", profile="AI") == []


class FakeResponse:
    """The collector streams the body now (there is a ceiling on how much a feed may
    send), so the double has to answer `iter_content` and the `with` protocol."""

    def __init__(self, text):
        self.text, self.content = text, text.encode()

    def raise_for_status(self):
        pass

    def iter_content(self, n=65536):
        yield self.content

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_collect_reads_every_configured_feed(monkeypatch):
    seen = []

    def fake_get(url, **kw):
        seen.append(url)
        return FakeResponse(RSS if "blog" in url else ATOM)

    monkeypatch.setattr("topicparser.collectors.feeds.requests.get", fake_get)
    c = FeedCollector()
    out = c.collect("AI", {"feeds": {"urls": ["https://blog.google/x/rss/",
                                              "https://youtube.com/feeds/videos.xml?channel_id=1"]}})
    assert len(seen) == 2
    assert len(out) == 3                       # two RSS items plus one Atom entry


def test_one_dead_feed_does_not_lose_the_others(monkeypatch):
    """Same rule as the GitHub topics and the X URLs: a source that fails is skipped
    and REPORTED, never allowed to discard what the others already returned."""
    def fake_get(url, **kw):
        if "dead" in url:
            raise RuntimeError("connection reset")
        return FakeResponse(RSS)

    monkeypatch.setattr("topicparser.collectors.feeds.requests.get", fake_get)
    warns = []
    c = FeedCollector()
    c.warn = warns.append
    out = c.collect("AI", {"feeds": {"urls": ["https://dead.example/rss", "https://ok/rss"]}})
    assert len(out) == 2
    assert len(warns) == 1 and "dead.example" in warns[0]


def test_a_repeated_link_across_feeds_is_kept_once(monkeypatch):
    monkeypatch.setattr("topicparser.collectors.feeds.requests.get",
                        lambda url, **kw: FakeResponse(RSS))
    c = FeedCollector()
    out = c.collect("AI", {"feeds": {"urls": ["https://a/rss", "https://b/rss"]}})
    assert len(out) == 2                       # the same two items, not four


def test_a_feed_is_capped_so_one_source_cannot_flood_the_run(monkeypatch):
    many = "".join(f"<item><title>t{i}</title><link>https://x/{i}</link></item>"
                   for i in range(60))
    monkeypatch.setattr("topicparser.collectors.feeds.requests.get",
                        lambda url, **kw: FakeResponse(f"<rss><channel>{many}</channel></rss>"))
    c = FeedCollector(limit=25)
    assert len(c.collect("AI", {"feeds": {"urls": ["https://x/rss"]}})) == 25


def test_stop_abandons_the_remaining_feeds(monkeypatch):
    import threading

    cancel = threading.Event()

    def fake_get(url, **kw):
        cancel.set()                           # Stop pressed while the first is in flight
        return FakeResponse(RSS)

    monkeypatch.setattr("topicparser.collectors.feeds.requests.get", fake_get)
    c = FeedCollector()
    c.cancel_event = cancel
    out = c.collect("AI", {"feeds": {"urls": ["https://a/rss", "https://b/rss", "https://c/rss"]}})
    assert len(out) == 2                       # only the first feed was read


def test_a_profile_with_no_feeds_costs_nothing(monkeypatch):
    called = []
    monkeypatch.setattr("topicparser.collectors.feeds.requests.get",
                        lambda url, **kw: called.append(url))
    c = FeedCollector()
    assert c.collect("AI", {"github": {"topics": ["mcp"]}}) == []
    assert c.collect("AI", {"feeds": {"urls": []}}) == []
    assert called == []


def test_a_thumbnail_is_never_mistaken_for_the_summary():
    """DeepMind's feed carries `<content medium="image" url="..."/>` on every item.
    Read as a description, that ships an image URL to the scorer as the signal's text.
    Their `<description>` is genuinely empty, so the right answer is no description."""
    feed = """<?xml version="1.0"?><rss version="2.0"><channel><item>
      <title>WeatherNext beats the physics models</title>
      <link>https://deepmind.google/blog/weathernext/</link>
      <description></description>
      <content medium="image" url="https://lh3.googleusercontent.com/abc=w528-h297"/>
    </item></channel></rss>"""
    sig = parse_feed(feed, profile="AI")[0]
    assert sig.description == ""
    assert "googleusercontent" not in sig.description


def test_a_title_only_feed_still_produces_a_signal():
    """Hugging Face publishes title + link + date and nothing else. The title of a
    blog post carries the news, so the signal is worth having."""
    feed = """<?xml version="1.0"?><rss version="2.0"><channel><item>
      <title>Making knowledge distillation cheap enough to run at scale</title>
      <link>https://huggingface.co/blog/efficient-distillation</link>
      <pubDate>Mon, 10 Aug 2026 10:05:00 GMT</pubDate>
    </item></channel></rss>"""
    sigs = parse_feed(feed, profile="AI")
    assert len(sigs) == 1 and sigs[0].description == ""
    assert sigs[0].date.startswith("2026-08-10T10:05")


def test_a_utf8_feed_survives_a_server_that_declares_no_charset():
    """`requests` falls back to ISO-8859-1 for `text/*` with no declared charset, so
    `r.text` turned Google's "We're launching" into "Weâre launching" and shipped the
    mojibake to the scorer. Bytes let ElementTree read the XML declaration instead."""
    raw = ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><item>'
           '<title>We’re launching Lyria 3.5</title>'
           '<link>https://blog.google/lyria</link>'
           '</item></channel></rss>').encode("utf-8")
    assert parse_feed(raw, profile="AI")[0].title == "We’re launching Lyria 3.5"
    # and the wrong way round is exactly the failure that was shipped
    assert "â" in raw.decode("latin-1")


def test_collect_hands_the_parser_bytes_not_text(monkeypatch):
    got = {}

    class Resp:
        content = '<?xml version="1.0" encoding="UTF-8"?><rss><channel></channel></rss>'.encode()
        text = "should not be used"

        def raise_for_status(self):
            pass

        def iter_content(self, n=65536):
            yield self.content

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("topicparser.collectors.feeds.requests.get", lambda url, **kw: Resp())
    monkeypatch.setattr("topicparser.collectors.feeds.parse_feed",
                        lambda xml, *a, **kw: got.setdefault("type", type(xml)) or [])
    FeedCollector().collect("AI", {"feeds": {"urls": ["https://x/rss"]}})
    assert got["type"] is bytes
