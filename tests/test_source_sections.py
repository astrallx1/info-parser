"""Official sources are a SOURCE, not "other".

A topic's section used to be read off its first LINK, which works for github.com and
x.com and fails for every blog: a lab's own announcement landed under «Інше» next to
whatever stray URL a cluster happened to carry. The signal always knew (`Signal.source`),
so the fix is to carry that through assembly, the DB and the export rather than sniff a
URL three times in three places.
"""
import json

from sqlalchemy import text as sa_text

from topicparser import export, ranker, store
from topicparser.models import Signal


def _sig(source, url, title="T"):
    return Signal.make(source=source, title=title, description="D", url=url,
                       date="2026-08-11T00:00:00+00:00", profile="AI")


# --- assembly ---------------------------------------------------------------------

def test_singleton_topic_carries_its_signal_source():
    survivors = [_sig("feed", "https://openai.com/index/x"),
                 _sig("github", "https://github.com/a/b"),
                 _sig("x", "https://x.com/u/status/1")]
    topics = ranker._assemble_topics(survivors, [80, 80, 80], ["a", "b", "c"],
                                     ["w", "w", "w"], {"groups": [], "stale": []})
    assert [t["source"] for t in topics] == ["feed", "gh", "tw"]


def test_cluster_source_prefers_github_then_x_then_feed():
    # a cluster mixing a blog post and the repo it announces is a GitHub topic: that is
    # the card that carries stars, and it is where the reader goes
    survivors = [_sig("feed", "https://openai.com/index/x"),
                 _sig("github", "https://github.com/a/b")]
    grouped = {"groups": [{"indices": [0, 1], "title": "G", "why": "W"}], "stale": []}
    topics = ranker._assemble_topics(survivors, [80, 90], ["a", "b"], ["w", "w"], grouped)
    assert len(topics) == 1 and topics[0]["source"] == "gh"

    survivors = [_sig("feed", "https://openai.com/index/x"),
                 _sig("x", "https://x.com/u/status/1")]
    topics = ranker._assemble_topics(survivors, [80, 90], ["a", "b"], ["w", "w"], grouped)
    assert topics[0]["source"] == "tw"


# --- persistence ------------------------------------------------------------------

def test_store_round_trips_the_source(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "t.db"))
    store.init_db()
    store.insert_topic(title="T", why="W", links=["https://openai.com/index/x"],
                       signature="s", score=80, profile="AI", source="feed")
    rows = store.get_recent_topics(days=30)
    assert rows and rows[0]["source"] == "feed"


def test_older_rows_without_a_source_still_read(tmp_path, monkeypatch):
    """The column is added by migration, so rows written before it exist have NULL —
    they must keep working rather than crash the feed."""
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "t.db"))
    store.init_db()
    tid = store.insert_topic(title="T", why="W", links=["https://github.com/a/b"],
                             signature="s", score=80, profile="AI")
    with store._session() as s:                       # simulate a pre-migration row
        s.execute(sa_text("UPDATE shown_topics SET source = NULL WHERE id = :i"),
                  {"i": tid})
        s.commit()
    rows = store.get_recent_topics(days=30)
    assert rows[0]["source"] in (None, "")            # no crash, no invention


# --- export -----------------------------------------------------------------------

def test_markdown_gives_official_sources_their_own_section():
    topics = [
        {"title": "GH", "why": "W", "score": 80, "source": "gh",
         "links": ["https://github.com/a/b"], "kept": 1},
        {"title": "Blog", "why": "W", "score": 95, "source": "feed",
         "links": ["https://openai.com/index/x"], "kept": 1},
        {"title": "Tweet", "why": "W", "score": 70, "source": "tw",
         "links": ["https://x.com/u/status/1"], "kept": 1},
        {"title": "Stray", "why": "W", "score": 99, "source": "other",
         "links": ["https://example.com/z"], "kept": 1},
    ]
    md = to_upper(export.to_markdown(topics, date="2026-08-11"))
    feeds_heading = to_upper(export.i18n.t("kind.feeds"))
    assert feeds_heading in md
    # order mirrors the feed: Twitter, GitHub, official sources, then anything else
    assert md.index("TWITTER") < md.index("GITHUB") < md.index(feeds_heading) < md.index(to_upper(export.i18n.t("source.other")))
    # and the blog topic is inside the official-sources section, not under "other"
    assert md.index("BLOG") > md.index(feeds_heading)


def test_markdown_falls_back_to_the_link_when_a_topic_has_no_source():
    """Rows written before the column existed still have to land somewhere sane."""
    topics = [{"title": "GH", "why": "W", "score": 80,
               "links": ["https://github.com/a/b"], "kept": 1}]
    md = export.to_markdown(topics, date="2026-08-11")
    assert "GITHUB" in to_upper(md)


def test_feed_link_is_labelled_by_its_host_not_the_raw_url():
    topics = [{"title": "Blog", "why": "W", "score": 80, "source": "feed",
               "links": ["https://openai.com/index/some-very-long-slug"], "kept": 1}]
    md = export.to_markdown(topics, date="2026-08-11")
    assert "[openai.com]" in md                       # the label
    assert "(https://openai.com/index/some-very-long-slug)" in md   # the href, whole


def to_upper(s):
    return s.upper()


# --- the run's own messages -------------------------------------------------------

def test_collect_phase_and_warning_name_the_feed_source_from_the_catalogue():
    """`_src_label` knew "github" and "x" and passed anything else through, so the
    status line read «Збираю feed…» and a failed fetch was labelled "feed" — an English
    identifier on screen in a Ukrainian build."""
    from topicparser import i18n, pipeline
    assert pipeline._src_label("feed") == i18n.t("kind.feeds")
    assert pipeline._src_label("github") == i18n.t("source.github")
    assert pipeline._src_label("x") == i18n.t("source.twitter")


def test_ui_names_every_source_and_never_prints_undefined():
    """The card badge read `SRC[key].label`, which only Twitter and GitHub carry: an
    «Інше» card printed the literal word "undefined"."""
    import pathlib
    ui = pathlib.Path("topicparser/ui/index.html").read_text(encoding="utf-8")
    assert "SRC[srcKey].label}" not in ui           # the raw read is gone
    assert "function srcLabel(" in ui               # one place names a source
    assert "feed:{icon:'newspaper'" in ui           # official sources are a section
    assert "const SRC_ORDER = ['tw', 'gh', 'feed', 'pod', 'other'];" in ui


def test_summary_line_uses_the_genitive_label_when_the_catalogue_has_one(monkeypatch):
    """«2 з Інше» is not Ukrainian. The section HEADING is nominative («ІНШЕ») and the
    summary needs the genitive, so a language that inflects supplies a `_of` variant and
    English simply does not."""
    real = export.i18n.t
    monkeypatch.setattr(export.i18n, "t",
                        lambda k, **f: "Першоджерел" if k == "kind.feeds_of" else real(k, **f))
    topics = [{"title": "Blog", "why": "W", "score": 80, "source": "feed",
               "links": ["https://openai.com/x"], "kept": 1}]
    md = export.to_markdown(topics, date="2026-08-11")
    assert "Першоджерел" in md.split("═")[0]        # in the summary line, above the sections


def test_summary_falls_back_to_the_plain_label_without_a_genitive_key():
    topics = [{"title": "T", "why": "W", "score": 80, "source": "gh",
               "links": ["https://github.com/a/b"], "kept": 1}]
    md = export.to_markdown(topics, date="2026-08-11")
    assert export.i18n.t("md.summary_item", n=1, source=export.i18n.t("source.github")) in md


def test_cleanup_uses_the_stored_source_not_the_link(tmp_path, monkeypatch):
    """The third place that sniffed links[0]. A tweet quoted in a cluster could sit
    first in the list and hand a GitHub topic X's five-day expiry; the stored source
    is what the topic actually came from."""
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "t.db"))
    store.init_db()
    gh = store.insert_topic(title="GH", why="W", score=80, profile="AI", signature="a",
                            links=["https://x.com/u/status/1", "https://github.com/a/b"],
                            source="gh")
    tw = store.insert_topic(title="TW", why="W", score=80, profile="AI", signature="b",
                            links=["https://x.com/u/status/2"], source="tw")
    store._backdate_topic(gh, 10)
    store._backdate_topic(tw, 10)

    store.cleanup_topics(x_days=5, gh_days=60)

    left = {t["title"] for t in store.get_recent_topics(days=365)}
    assert left == {"GH"}, "the GitHub topic survived on its own source, the tweet expired"


def test_a_podcast_expires_on_the_feed_window_not_the_github_one(tmp_path, monkeypatch):
    """`_topic_window` knew three sources and `pod` was not one of them, so a podcast
    fell through to the GitHub window — the exact shape of the bug this function was
    written against, one source kind further along. Harmless while GH_FRESH_DAYS (60)
    is the widest of the three; the moment it is narrowed below FEED_FRESH_DAYS the row
    is deleted early, falls out of `seen_links` with it (which reads the WIDEST window),
    and the episode is collected, scored and shown a second time."""
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "t.db"))
    store.init_db()
    pod = store.insert_topic(title="POD", why="W", score=80, profile="AI", signature="p",
                             links=["https://example.com/ep/1"], source="pod")
    store._backdate_topic(pod, 10)

    store.cleanup_topics(x_days=3, gh_days=5, feed_days=30)

    left = {t["title"] for t in store.get_recent_topics(days=365)}
    assert left == {"POD"}, "the podcast expired on the GitHub window"
