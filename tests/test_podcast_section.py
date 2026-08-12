"""A podcast topic must be distinguishable from a lab's own blog post.

`Signal.first_party` decided which feed posts `gate_feeds` judges, and then died
there: `_assemble_topics` stamped every feed signal `feed`, so an interview with a
guest and OpenAI's own release note landed in one section of the feed and one
section of the `.md`. The split existed in the config, the collector and the gate,
and stopped one step before the only surface the owner reads.
"""
import json

from topicparser import export, i18n
from topicparser.models import Signal
from topicparser.ranker import _assemble_topics, _cluster_source, _source_key


def _sig(source, title, *, first_party=True, url="https://example.com/a"):
    return Signal.make(source=source, title=title, description="d", url=url,
                       date="2026-08-30", profile="AI", first_party=first_party)


def test_source_key_separates_a_podcast_from_a_first_party_feed():
    lab = _sig("feed", "OpenAI ships something")
    show = _sig("feed", "A guest on somebody's show", first_party=False)
    assert _source_key(lab) == "feed"
    assert _source_key(show) == "pod"


def test_other_sources_keep_their_keys_whatever_first_party_says():
    # first_party defaults True and is meaningless off a feed; a tweet carrying
    # False must not become a podcast.
    assert _source_key(_sig("github", "owner/repo", first_party=False)) == "gh"
    assert _source_key(_sig("x", "@somebody", first_party=False)) == "tw"


def test_a_cluster_holding_a_lab_post_and_a_podcast_is_a_lab_post():
    # The strongest source in a cluster wins, and a lab talking about its own
    # release outranks a show discussing it.
    mixed = [_sig("feed", "A guest on a show", first_party=False),
             _sig("feed", "The lab's own note")]
    assert _cluster_source(mixed) == "feed"


def test_assembled_topics_carry_the_podcast_source():
    survivors = [_sig("feed", "Lab note"),
                 _sig("feed", "Show episode", first_party=False)]
    topics = _assemble_topics(survivors, [80, 75], ["Lab note", "Show episode"],
                              ["r", "r"], {"groups": [], "stale": []})
    by_title = {t["title"]: t["source"] for t in topics}
    assert by_title["Lab note"] == "feed"
    assert by_title["Show episode"] == "pod"


def test_the_md_gives_podcasts_their_own_section():
    keys = [k for k, _ in export._SOURCE_KEYS]
    assert "pod" in keys, "the export has no podcast section"
    # Order mirrors the feed: podcasts sit after the first-party sources, before
    # the catch-all.
    assert keys.index("feed") < keys.index("pod") < keys.index("other")

    md = export.to_markdown(
        [{"title": "Show episode", "why": "w", "score": 75, "source": "pod",
          "links": ["https://www.youtube.com/watch?v=x"]},
         {"title": "Lab note", "why": "w", "score": 80, "source": "feed",
          "links": ["https://openai.com/index/x"]}],
        date="2026-08-30")
    assert i18n.t("kind.interviews") in md
    assert i18n.t("kind.feeds") in md


def test_the_catalogue_labels_the_podcast_section():
    # Every user-visible string comes from a catalogue; a missing key renders as
    # the raw dotted name.
    assert i18n.t("kind.interviews") != "kind.interviews"


def test_the_ui_renders_the_same_four_sections_in_the_same_order():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "topicparser", "ui", "index.html"),
              encoding="utf-8") as f:
        html = f.read()
    assert "pod:{icon:" in html.replace(" ", ""), "the UI has no podcast source entry"
    order = html.split("const SRC_ORDER =")[1].split(";")[0]
    assert "'pod'" in order
    assert order.index("'feed'") < order.index("'pod'") < order.index("'other'")


def test_the_feed_groups_every_source_it_can_render():
    """The seventh place, missed for two days and shipped to both repos.

    `1843cfb` added 'pod' to `SRC_ORDER` and to `sourceOf`, and left the grouping
    literal in `renderResults` at four keys — so `groups[sourceOf(t)]` was `undefined`
    for a podcast topic and `.push` threw. The whole feed then rendered NOTHING: no
    cards, the status stuck on «Працює…», the `.md` button armed over a blank screen,
    after a paid sixteen-minute run. Caught by driving the stub harness, not by
    reading, because the source looks right in both places separately.

    The literal is now DERIVED from `SRC_ORDER`, so the two cannot drift again; this
    pins that, rather than pinning a second hand-written list."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "topicparser", "ui", "index.html"),
              encoding="utf-8") as f:
        html = f.read()
    body = html[html.index("function renderResults("):]
    body = body[:body.index("\n}")]
    line = next(l for l in body.splitlines() if "const groups" in l)
    assert "SRC_ORDER" in line, \
        f"the feed groups topics by a hand-written list again: {line.strip()}"
