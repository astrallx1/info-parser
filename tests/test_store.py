import topicparser.store as store

def _fresh(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db")
    store.init_db()

def test_insert_and_recent_topics(tmp_path):
    _fresh(tmp_path)
    tid = store.insert_topic(title="Claude 5 released", why="big",
                             links=["https://x.com/a/status/1"],
                             signature="claude 5 release", score=90, profile="AI")
    assert tid > 0
    recent = store.get_recent_topics(days=7)
    assert recent[0]["title"] == "Claude 5 released"
    assert recent[0]["links"] == ["https://x.com/a/status/1"]

def test_seen_links_collects_all_links(tmp_path):
    _fresh(tmp_path)
    store.insert_topic(title="t", why="w", links=["https://a/1", "https://a/2"],
                       signature="s", score=90, profile="AI")
    assert store.seen_links(days=30) == {"https://a/1", "https://a/2"}

def test_cleanup_deletes_old(tmp_path):
    _fresh(tmp_path)
    tid = store.insert_topic(title="old", why="w", links=[], signature="s",
                             score=90, profile="AI")
    store._backdate_topic(tid, days=40)          # test helper
    store.cleanup_topics(x_days=7, gh_days=21)
    assert store.get_recent_topics(days=999) == []

def test_cleanup_expires_x_topic_on_x_window(tmp_path):
    # an X-sourced topic (first link x.com) must expire on the short X window,
    # even though its profile name ("AI") contains no "x"
    _fresh(tmp_path)
    tid = store.insert_topic(title="x topic", why="w",
                             links=["https://x.com/a/status/1"],
                             signature="s", score=90, profile="AI")
    store._backdate_topic(tid, days=10)          # > x_days=5, < gh_days=21
    store.cleanup_topics(x_days=5, gh_days=21)
    assert store.get_recent_topics(days=999) == []

def test_cleanup_keeps_github_topic_within_gh_window(tmp_path):
    # a GitHub-sourced topic survives the longer GitHub window
    _fresh(tmp_path)
    tid = store.insert_topic(title="gh topic", why="w",
                             links=["https://github.com/a/b"],
                             signature="s", score=90, profile="AI")
    store._backdate_topic(tid, days=10)          # > x_days=5, < gh_days=21
    store.cleanup_topics(x_days=5, gh_days=21)
    kept = store.get_recent_topics(days=999)
    assert len(kept) == 1 and kept[0]["title"] == "gh topic"


def test_checkpoint_lands_writes_in_main_db_file(tmp_path):
    # WAL mode strands recent writes in the -wal sidecar; checkpoint() must merge
    # them into topics.db so copying that file alone doesn't lose data.
    import sqlite3
    _fresh(tmp_path)
    store.insert_topic(title="t", why="w", links=["u"], signature="s",
                       score=90, profile="AI")
    store.checkpoint()
    db = str(tmp_path / "t.db")
    # immutable read ignores the -wal sidecar -> proves the row is in the main file
    c = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
    n = c.execute("select count(*) from shown_topics").fetchone()[0]
    c.close()
    assert n == 1


def test_close_checkpoints_and_stays_usable(tmp_path):
    import sqlite3
    _fresh(tmp_path)
    store.insert_topic(title="t", why="w", links=["u"], signature="s",
                       score=90, profile="AI")
    store.close()
    db = str(tmp_path / "t.db")
    c = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
    assert c.execute("select count(*) from shown_topics").fetchone()[0] == 1
    c.close()
    # engine was disposed; the store rebuilds lazily and still reads the data
    assert len(store.get_recent_topics(days=7)) == 1


# --- a feed topic expires on the FEED window ---------------------------------------
#
# `cleanup_topics` knew two windows, X and everything-else, so a feed topic lived
# `GH_FRESH_DAYS`. Narrow GitHub (its minimum is 1) and leave feeds at 30 and a blog
# post shown 20 days ago is deleted, drops out of `seen_links`, and is collected,
# scored and shown again. Both halves have to move together: widening `seen_links`
# alone finds nothing, because the row is already gone by then.


def _feed_topic(days_ago, source="feed"):
    tid = store.insert_topic(title="Lab ships a model", why="why",
                             links=["https://openai.com/index/x"], signature="s",
                             score=90, profile="AI", source=source)
    store._backdate_topic(tid, days_ago)
    return "https://openai.com/index/x"


def test_a_feed_topic_survives_inside_the_feed_window(tmp_path):
    _fresh(tmp_path)
    link = _feed_topic(20)

    store.cleanup_topics(x_days=3, gh_days=14, feed_days=30)

    assert link in store.seen_links(days=max(3, 14, 30))


def test_a_feed_topic_older_than_the_feed_window_goes(tmp_path):
    _fresh(tmp_path)
    _feed_topic(40)

    store.cleanup_topics(x_days=3, gh_days=14, feed_days=30)

    assert store.get_recent_topics(days=365) == []


def test_a_legacy_row_with_no_source_still_uses_the_github_window(tmp_path):
    """The links[0] fallback can spot X and nothing else — a blog URL is
    indistinguishable from any other link — so a feed topic written before the `source`
    column keeps the old behaviour rather than a guess."""
    _fresh(tmp_path)
    _feed_topic(20, source=None)         # written before the column existed

    store.cleanup_topics(x_days=3, gh_days=14, feed_days=30)

    assert store.get_recent_topics(days=365) == []
