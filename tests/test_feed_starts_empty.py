"""The feed is the CURRENT session's run, and nothing else.

It used to be restored from the database on launch — added 2026-08-17, because closing
the app emptied the screen and killed the `.md` button while sixty days of topics sat
in `shown_topics` reachable by nothing. **The owner removed it on 2026-09-04**: he runs,
reads the feed, saves the `.md`, and that FILE is the artifact. A previous run still on
screen when he opens the app is clutter, not a saved result.

What stays: `store.get_last_run_topics` — the `.md` scope is still one run, and the rows
still live in the database, because cross-run dedup is what stops a topic arriving
twice. What goes with it: `Api.get_saved_topics`, and the «clear» button, which only
ever existed because a screen-only clear came back on the next launch.

The consequence is deliberate: `_last_topic_ids` is memory-only, so after a restart
there is nothing to export. One run, one file, saved in the session that made it."""
import topicparser.store as store
from topicparser.api import Api


def _insert(run_id, title, **kw):
    return store.insert_topic(title=title, why="w", links=[f"https://x.com/{title}"],
                              signature=title.lower(), score=90, profile="AI",
                              run_id=run_id, **kw)


def test_topics_remember_which_run_produced_them(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    _insert("2026-08-17T10:00:00", "A")
    _insert("2026-08-17T10:00:00", "B")
    _insert("2026-08-17T12:00:00", "C")
    assert sorted(t["title"] for t in store.get_last_run_topics()) == ["C"]


def test_the_last_run_keeps_every_topic_it_produced(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    _insert("r1", "old")
    _insert("r2", "A"); _insert("r2", "B")
    assert sorted(t["title"] for t in store.get_last_run_topics()) == ["A", "B"]


def test_an_empty_database_returns_nothing(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    assert store.get_last_run_topics() == []


def test_rows_written_before_the_column_existed_are_ignored(tmp_path):
    # `run_id` is nullable and old rows carry NULL; they must not all read as one
    # giant "last run".
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    store.insert_topic(title="ancient", why="w", links=["u"], signature="s",
                       score=90, profile="AI")
    _insert("r1", "A")
    assert [t["title"] for t in store.get_last_run_topics()] == ["A"]


def test_the_api_offers_no_way_to_redraw_a_past_run():
    """The bridge is the only JS->Python surface, so removing the method IS removing
    the feature — there is no other door to the screen."""
    assert not hasattr(Api, "get_saved_topics")


def test_the_export_is_dead_until_a_run_arms_it(tmp_path):
    """`_last_topic_ids` starts empty and only `run_parser` fills it, so a fresh app
    over a full database exports nothing rather than yesterday's run."""
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    _insert("r1", "A"); _insert("r1", "B")
    api = Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
              threshold=70, x_days=3, gh_days=60)

    assert api._md_topics() == []
    assert api.save_md(str(tmp_path / "out.md")) == {"ok": False, "empty": True}


def test_the_rows_themselves_are_untouched(tmp_path):
    """Not drawing them is not deleting them: dedup reads these on the next run."""
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    _insert("r1", "A"); _insert("r1", "B")

    assert len(store.get_last_run_topics()) == 2
    assert store.count_all()["topics"] == 2
