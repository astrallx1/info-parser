"""The feed used to die with the window.

Sixty days of topics sit in `shown_topics`, and nothing in the API handed them back:
the screen only ever drew the return value of `run_parser`. Close the app and the feed
was empty, the `.md` could no longer be saved (`_last_topic_ids` is memory-only), and
the only way to see the work again was to pay for another run.

Restoring THE LAST RUN — not sixty days of everything — is what matters: that is the
scope the feed shows and the scope one `.md` covers."""
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


def test_api_hands_the_last_run_back_to_the_screen(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    _insert("r1", "A"); _insert("r1", "B")
    api = Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
              threshold=70, x_days=3, gh_days=60)
    out = api.get_saved_topics()
    assert sorted(t["title"] for t in out["topics"]) == ["A", "B"]


def test_restoring_the_feed_also_restores_the_md_export(tmp_path):
    # `_last_topic_ids` is memory-only, so after a restart the .md button was dead
    # even though the topics were right there in the database.
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    ids = [_insert("r1", "A"), _insert("r1", "B")]
    api = Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
              threshold=70, x_days=3, gh_days=60)
    api.get_saved_topics()
    assert sorted(t["id"] for t in api._md_topics()) == sorted(ids)


def test_a_dropped_topic_does_not_come_back(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    a = _insert("r1", "A"); _insert("r1", "B")
    store.set_kept(a, False)
    api = Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
              threshold=70, x_days=3, gh_days=60)
    # it is still RENDERED, with its checkbox off, exactly as before a restart...
    assert sorted(t["title"] for t in api.get_saved_topics()["topics"]) == ["A", "B"]
    assert [t["title"] for t in api._md_topics()] == ["B"]   # ...but never EXPORTED
