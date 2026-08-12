"""`Api.reset_database` passes the checkbox choice through, and guards it."""
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
    store.add_tracked_repo("a/b")
    store.record_stars("a/b", 10)
    store.ban_repo("bad/repo")


def test_only_the_selected_parts_go(tmp_path):
    _seed(tmp_path)
    api = _api()

    res = api.reset_database({"topics": True, "tracked": False, "banned": False})

    assert res["ok"] is True
    assert api.db_stats() == {"topics": 0, "tracked": 1, "stars": 1, "banned": 1}


def test_selecting_nothing_is_refused_rather_than_silently_doing_nothing(tmp_path):
    _seed(tmp_path)
    api = _api()

    res = api.reset_database({"topics": False, "tracked": False, "banned": False})

    assert "errors" in res
    assert api.db_stats()["topics"] == 1


def test_the_export_scope_is_only_forgotten_when_topics_go(tmp_path):
    """Wiping just the ban list must not disarm the .md button — those topics are
    still in the table."""
    _seed(tmp_path)
    api = _api()
    api._last_topic_ids = {1}

    api.reset_database({"topics": False, "tracked": False, "banned": True})

    assert api._last_topic_ids == {1}


def test_wiping_topics_forgets_the_export_scope(tmp_path):
    _seed(tmp_path)
    api = _api()
    api._last_topic_ids = {1}

    api.reset_database({"topics": True, "tracked": False, "banned": False})

    assert api._last_topic_ids == set()


def test_no_argument_still_wipes_everything(tmp_path):
    _seed(tmp_path)
    api = _api()

    api.reset_database()

    assert api.db_stats() == {"topics": 0, "tracked": 0, "stars": 0, "banned": 0}
