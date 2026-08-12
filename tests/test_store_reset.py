"""Wiping the database from Settings.

The owner asked for it as a Settings button. It is the most destructive thing the app
can do — shown topics, the watchlist, the star history that trending is derived from,
and the ban list all go — so it backs the file up first and reports what it removed,
and the UI confirms twice before calling it.
"""
import os

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


def test_reset_reports_what_it_is_about_to_remove(tmp_path):
    _seed(tmp_path)

    counts = store.count_all()

    assert counts == {"topics": 1, "tracked": 1, "stars": 1, "banned": 1}


def test_reset_empties_every_table(tmp_path):
    _seed(tmp_path)

    store.reset_all()

    assert store.count_all() == {"topics": 0, "tracked": 0, "stars": 0, "banned": 0}


def test_reset_backs_the_file_up_first(tmp_path):
    _seed(tmp_path)

    backup = store.reset_all()

    assert backup and os.path.exists(backup)
    assert ".backup-" in backup            # stamped, so the next wipe cannot eat it


def test_the_database_still_works_after_a_reset(tmp_path):
    """It empties the tables rather than deleting the file — the next run must not
    have to recreate anything."""
    _seed(tmp_path)

    store.reset_all()
    store.insert_topic(title="NEW", why="w", links=["u"], signature="s2",
                       score=80, profile="AI")

    assert store.count_all()["topics"] == 1


def test_reset_on_a_fresh_database_is_harmless(tmp_path):
    store.DB_PATH = str(tmp_path / "fresh.db")
    store.close()
    store.init_db()

    store.reset_all()

    assert store.count_all() == {"topics": 0, "tracked": 0, "stars": 0, "banned": 0}
