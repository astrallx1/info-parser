import re

from topicparser import i18n


def _link_label(url: str) -> tuple[str, str]:
    """(source_tag, readable_label) for a link — so the .md shows `owner/repo`
    or `@handle` as a clickable label instead of a raw URL."""
    m = re.search(r"github\.com/([^/]+/[^/?#]+)", url)
    if m:
        return "GitHub", m.group(1)
    m = re.search(r"(?:x|twitter)\.com/([^/?#]+)/status", url)
    if m:
        return "X", "@" + m.group(1)
    # Anything else is a blog or a video: the HOST is what names it ("openai.com"),
    # while the raw address is a slug nobody reads. The href keeps the whole URL.
    m = re.search(r"https?://(?:www\.)?([^/?#]+)", url)
    if m:
        return "", m.group(1)
    return "", url


def _local_today() -> str:
    """The owner's calendar day, not UTC — the file is dated for the person saving
    it, and `Api._md_filename` already names it the same way."""
    from datetime import date
    return date.today().isoformat()


def write_markdown(topics: list[dict], path: str, date: str = None,
                   alerts: list[dict] = None) -> str:
    if date is None:
        date = _local_today()
    with open(path, "w", encoding="utf-8") as f:
        f.write(to_markdown(topics, date=date, alerts=alerts))
    return path


# source sections, IDENTICAL to the tool feed (ui `renderResults`): Twitter first,
# then GitHub, then anything else. The .md is what the user reviews/picks against, so
# its structure must mirror the feed exactly — no profile grouping (the feed has none).
_SOURCE_KEYS = [("tw", "source.twitter"), ("gh", "source.github"),
                ("feed", "kind.feeds"), ("other", "source.other")]


def _summary_label(key: str) -> str:
    """The summary line reads "{n} from {source}", which in an inflected language is not
    the same word as the section heading: in Ukrainian the heading form is wrong there
    and the genitive is right.
    A catalogue may supply a `<key>_of` variant; English has no case to change, so it
    supplies none and this falls straight back to the heading."""
    of = i18n.t(key + "_of")
    return i18n.t(key) if of == key + "_of" else of


def _topic_source(t: dict) -> str:
    """'tw' / 'gh' / 'feed' / 'other', mirroring the feed's `sourceOf`.

    The topic CARRIES its source now (the ranker reads it off the signal). The link
    sniffing below is only the fallback for rows written before that column existed:
    it cannot tell a lab blog from any other address, which is exactly why official
    sources used to pile up in the catch-all section."""
    from topicparser.ranker import _SOURCE_KEY   # one map, defined where it is stamped
    known = (t.get("source") or "").lower()
    if known in set(_SOURCE_KEY.values()) | {"other"}:
        return known
    links = t.get("links") or []
    l = (links[0] if links else "").lower()
    if "github.com" in l:
        return "gh"
    if "x.com" in l or "twitter.com" in l:
        return "tw"
    return "other"


# readability furniture (the file is a wall of many topics — space it out)
_RULE = "═" * 24            # boxed section header (box-drawing, not `=`, so no setext H1)
_POST_SEP = "· · · · · · · · · · · · ·"   # soft divider between posts in a section


def _oneline(s: str) -> str:
    """A heading is a LINE. A `why` or a title carrying a newline ends its heading
    early and orphans the rest of the text at the top level of the file."""
    return " ".join(str(s or "").split())


def _topic_block(t: dict) -> str:
    b = [f"### {_oneline(t['title'])}"]
    if t.get("score") is not None:
        b.append(f"`{i18n.t('md.score', score=t['score'])}`")
    if t.get("why"):
        b += ["", t["why"]]
    b.append("")
    for l in t.get("links", []):
        src, label = _link_label(l)
        prefix = f"**{src}** " if src else ""
        b.append(f"→ {prefix}[{label}]({l})")
    return "\n".join(b)


def _stars(n) -> str:
    """2654 -> '2 654' (uk) or '2,654' (en). The separator comes from the catalogue,
    same as the feed's — hardcoding it here meant the .md and the screen could show
    the same number two different ways."""
    return f"{int(n):,}".replace(",", i18n.t("locale.thousands"))


def _alert_block(a: dict) -> str:
    """One trending repo. Not a topic — no score, no kept flag; it comes off the
    watchlist and bypasses the whole topic pipeline, so it gets its own shape."""
    b = [f"### [{a.get('repo','')}]({a.get('url','')})"]
    metric = []
    if a.get("velocity") is not None:
        metric.append(f"`+{round(a['velocity'])} " + i18n.t('md.velocity_unit') + "`")
    if a.get("stars") is not None:
        metric.append(f"`{_stars(a['stars'])} ★`")
    if metric:
        b.append(" · ".join(metric))
    if a.get("description"):
        b += ["", a["description"]]
    return "\n".join(b)


def _trending_section(alerts: list[dict]) -> str:
    rows = sorted(alerts, key=lambda a: -(a.get("velocity") or 0))
    head = f"{_RULE}\n##  {i18n.t('md.trending_heading')}  ({len(rows)})\n{_RULE}"
    body = f"\n\n{_POST_SEP}\n\n".join(_alert_block(a) for a in rows)
    return f"{head}\n\n{body}"


def to_markdown(topics: list[dict], date: str, alerts: list[dict] = None) -> str:
    # trending leads the file, exactly as it leads the feed
    trending = _trending_section(alerts) if alerts else ""

    title = f"# {i18n.t('md.title', date=date)}"
    kept = [t for t in topics if t.get("kept", 1)]
    if not kept:
        head = f"{title}\n\n_{i18n.t('md.empty')}_\n"
        return f"{head}\n{trending}\n" if trending else head

    # group by SOURCE (not profile) so the file mirrors the tool feed exactly
    groups: dict[str, list[dict]] = {key: [] for key, _ in _SOURCE_KEYS}
    for t in kept:
        groups[_topic_source(t)].append(t)

    present = [(key, i18n.t(k), _summary_label(k)) for key, k in _SOURCE_KEYS if groups[key]]
    summary = " · ".join(i18n.t("md.summary_item", n=len(groups[key]), source=of)
                         for key, label, of in present)
    header = f"{title}\n\n**{summary}**"

    sections = []
    for key, label, _of in present:
        rows = sorted(groups[key], key=lambda x: -(x.get("score") or 0))
        head = f"{_RULE}\n##  {label.upper()}  ({len(rows)})\n{_RULE}"
        body = f"\n\n{_POST_SEP}\n\n".join(_topic_block(t) for t in rows)
        sections.append(f"{head}\n\n{body}")

    if trending:
        sections.insert(0, trending)
    return header + "\n\n" + "\n\n".join(sections) + "\n"
