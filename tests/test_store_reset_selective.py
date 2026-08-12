"""Wiping only the parts you picked.

The owner wanted checkboxes rather than an all-or-nothing button: the watchlist and its
star history are worth months of measurement, while the shown-topics table is the one
you actually want to clear before a verify run.
"""
from topicparser import store


def _seed(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db")
    store.close()
    store.init_db()
    store.insert_topic(title="T", why="w", links=["https://github.com/a/b"],
                       signature="s", score=90, profile="AI")
    store.add_tracked_repo("a/b", description="опис")
    store.record_stars("a/b", 100)
    store.ban_repo("bad/repo")


def test_wiping_only_the_topics_leaves_everything_else(tmp_path):
    _seed(tmp_path)

    store.reset_all(topics=True, tracked=False, banned=False)

    assert store.count_all() == {"topics": 0, "tracked": 1, "stars": 1, "banned": 1}


def test_wiping_the_watchlist_takes_its_star_history_with_it(tmp_path):
    """A tracked repo with no history is a row that can never show a velocity —
    the two belong to the same choice."""
    _seed(tmp_path)

    store.reset_all(topics=False, tracked=True, banned=False)

    assert store.count_all() == {"topics": 1, "tracked": 0, "stars": 0, "banned": 1}


def test_wiping_only_the_ban_list(tmp_path):
    _seed(tmp_path)

    store.reset_all(topics=False, tracked=False, banned=True)

    assert store.count_all() == {"topics": 1, "tracked": 1, "stars": 1, "banned": 0}


def test_picking_nothing_changes_nothing_and_writes_no_backup(tmp_path):
    _seed(tmp_path)

    assert store.reset_all(topics=False, tracked=False, banned=False) is None
    assert store.count_all() == {"topics": 1, "tracked": 1, "stars": 1, "banned": 1}


def test_everything_selected_is_still_the_default(tmp_path):
    _seed(tmp_path)

    store.reset_all()

    assert store.count_all() == {"topics": 0, "tracked": 0, "stars": 0, "banned": 0}
