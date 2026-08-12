"""The Settings button that wipes the database."""
from topicparser import store
from topicparser.api import Api


def _api():
    return Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
               threshold=70, x_days=3, gh_days=60)


def _seed(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db")
    store.close()
    store.init_db()
    store.insert_topic(title="T", why="w", links=["u"], signature="s", score=90, profile="AI")
    store.ban_repo("bad/repo")


def test_db_stats_report_the_counts(tmp_path):
    _seed(tmp_path)

    assert _api().db_stats() == {"topics": 1, "tracked": 0, "stars": 0, "banned": 1}


def test_reset_database_wipes_and_reports_the_backup(tmp_path):
    _seed(tmp_path)
    api = _api()

    res = api.reset_database()

    assert res["ok"] is True
    assert ".backup-" in res["backup"]      # one stamped copy per wipe
    assert api.db_stats() == {"topics": 0, "tracked": 0, "stars": 0, "banned": 0}


def test_reset_forgets_the_last_run_so_the_md_button_dies_with_it(tmp_path):
    """The export scope is the last run's topics; after a wipe those rows are gone,
    so offering to export them would write an empty file."""
    _seed(tmp_path)
    api = _api()
    api._last_topic_ids = {1}

    api.reset_database()

    assert api._last_topic_ids == set()
    assert api.save_md("/tmp/should-not-be-written.md") == {"ok": False, "empty": True}


def test_reset_is_refused_while_a_run_is_in_flight(tmp_path):
    """Half the run's writes would land after the wipe."""
    _seed(tmp_path)
    api = _api()
    api._running = True

    res = api.reset_database()

    assert "errors" in res
    assert api.db_stats()["topics"] == 1
