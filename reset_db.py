#!/usr/bin/env python3
"""Wipe the local topics DB for a clean test run.

  .venv/bin/python reset_db.py         # dry run — shows row counts, changes nothing
  .venv/bin/python reset_db.py --yes   # backup to topics.db.backup-<time>, then wipe every table

Close the app first (SQLite locks the file while it runs).
DB path comes from DB_PATH (.env), default ./topics.db. The backup is gitignored.
"""
import os, shutil, sqlite3, sys

# Read `.env` and anchor the path the same way the app does. Without this the script
# only saw DB_PATH when it happened to be exported in the shell, so anybody with a
# custom path was told "nothing to wipe" while the real database sat untouched.
from topicparser import config

DB = config.env_path("DB_PATH", "./topics.db")


def tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return [r[0] for r in rows]


def main():
    if not os.path.exists(DB):
        print(f"{DB} does not exist — nothing to wipe (a fresh DB is created on next run).")
        return
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA wal_checkpoint(FULL)")
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables(conn)}
    print(f"{DB} current rows: " + ", ".join(f"{t}={n}" for t, n in counts.items()))

    if "--yes" not in sys.argv:
        print("dry run. re-run with --yes to back up + wipe.")
        return

    conn.close()
    from datetime import datetime
    backup = f"{DB}.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(DB, backup)
    print(f"backed up -> {backup}")

    conn = sqlite3.connect(DB)
    for t in tables(conn):
        conn.execute(f"DELETE FROM {t}")
    conn.commit()
    conn.execute("VACUUM")
    conn.close()
    print("wiped every table. base is clean.")


if __name__ == "__main__":
    main()
