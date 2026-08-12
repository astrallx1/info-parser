import sqlite3
import topicparser.store as store


def test_init_db_migrates_old_tracked_table_missing_columns(tmp_path):
    # simulate a DB created by an older schema: tracked_repos without
    # description / last_growing (the exact shape that caused the live crash)
    p = str(tmp_path / "old.db")
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE tracked_repos (repo TEXT PRIMARY KEY, added TEXT)")
    con.commit(); con.close()

    store.DB_PATH = p
    store.init_db()                       # must add the missing columns, not crash

    store.add_tracked_repo("owner/repo", description="a tool")
    row = store.get_tracked_detail()[0]   # selects description + last_growing
    assert row["repo"] == "owner/repo"
    assert row["description"] == "a tool"


def _indexes(path, table):
    con = sqlite3.connect(path)
    try:
        return {r[1] for r in con.execute(f"PRAGMA index_list({table})")}
    finally:
        con.close()


def test_star_history_is_indexed_by_repo(tmp_path):
    """Every velocity reads one repo's whole history now, and `detect_trending` does it
    once per tracked repo. Unindexed that is a full scan of `star_history` per repo,
    growing as rows x repos — it used to be bounded by a LIMIT 2."""
    p = str(tmp_path / "fresh.db")
    store.DB_PATH = p
    store.init_db()

    assert "ix_star_history_repo" in _indexes(p, "star_history")


def test_an_existing_db_gains_the_index_too(tmp_path):
    """It belongs in `_migrate`, not in the model: `create_all` skips a table that
    already exists, so a DB in the field would never gain an index declared there."""
    p = str(tmp_path / "old.db")
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE star_history "
                "(id INTEGER PRIMARY KEY, repo TEXT, stars INTEGER, timestamp TEXT)")
    con.commit(); con.close()

    store.DB_PATH = p
    store.init_db()

    assert "ix_star_history_repo" in _indexes(p, "star_history")
