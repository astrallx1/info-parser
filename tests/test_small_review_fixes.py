"""The small findings from the 2026-08-19 review, each with the failure it produces."""
import threading

from topicparser import api as api_mod, notify, prompts_loader
from topicparser import store


# --- osascript escaping -------------------------------------------------------------
def test_a_backslash_in_a_notification_does_not_break_the_applescript(monkeypatch):
    # AppleScript string literals treat \ as an escape, so a Windows-style path or a
    # regex in an error message would end the literal early and the notification is
    # silently lost. Only " was neutralised.
    seen = {}
    monkeypatch.setattr(notify.shutil, "which", lambda n: "/usr/bin/osascript")
    monkeypatch.setattr(notify.subprocess, "run", lambda cmd, **kw: seen.update(cmd=cmd))
    notify._send_mac_osascript("t", r"C:\temp\run", "Ping")
    script = seen["cmd"][-1]
    assert r"\\temp" in script          # the backslash is escaped, not raw
    assert script.count('"') == 6       # three literals, none opened by the payload


# --- a deleted profile must not leave its rules behind ------------------------------
def test_deleting_a_profile_takes_its_backup_with_it(tmp_path, monkeypatch):
    # save_profile_prompt keeps one previous version as <name>.bak.txt. Deleting the
    # profile removed <name>.txt only, so recreating a profile under the same name
    # offered "restore the previous version" and handed back a stranger's rules.
    # patch the ONE seam both paths go through: `_backup_path` deliberately no longer
    # calls `write_dir`, since asking whether a backup exists must not create a folder
    monkeypatch.setattr(prompts_loader.paths, "app_dir", lambda: str(tmp_path))
    prompts_loader.save_profile_prompt("Crypto", "first rules")
    prompts_loader.save_profile_prompt("Crypto", "second rules")     # writes the .bak
    d = tmp_path / "prompts"
    assert (d / "Crypto.bak.txt").exists()

    assert prompts_loader.delete_profile_prompt("Crypto") == []
    assert not (d / "Crypto.bak.txt").exists()


# --- the run guard is a lock on every door ------------------------------------------
def _api(tmp_path, **kw):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    return api_mod.Api(profiles={"profiles": {}}, build_collectors=lambda: [],
                       build_client=lambda: None, threshold=80,
                       x_days=kw.pop("x_days", 3), gh_days=kw.pop("gh_days", 21), **kw)


def test_settings_writes_take_the_run_lock(tmp_path):
    # `_running` was read here without the lock that run_parser sets it under, so a
    # save could pass the check while a run was starting and land mid-run.
    a = _api(tmp_path)
    a._run_lock = _WatchedLock(a._run_lock)
    a._running = True
    assert a.save_tuning({"SCORE_THRESHOLD": 80}).get("errors")
    assert a.reset_database(["topics"]).get("errors")
    assert a._run_lock.taken >= 2


class _WatchedLock:
    def __init__(self, inner):
        self._inner = inner
        self.taken = 0

    def __enter__(self):
        self.taken += 1
        return self._inner.__enter__()

    def __exit__(self, *a):
        return self._inner.__exit__(*a)


# --- the export window cannot go stale ----------------------------------------------
def test_export_finds_the_last_run_whatever_the_freshness_knobs_say(tmp_path):
    # _md_topics filtered by the x/gh windows this Api was CONSTRUCTED with, while
    # every other knob is resolved at run time. The last run is the last run.
    a = _api(tmp_path, x_days=0, gh_days=0)
    tid = store.insert_topic(title="T", why="w", links=["https://e.com/1"],
                             signature="t", score=90, profile="AI", run_id="r1")
    a._last_topic_ids = {tid}
    assert [t["title"] for t in a._md_topics()] == ["T"]


def test_the_write_itself_happens_under_the_run_lock(tmp_path, monkeypatch):
    # reading the flag under the lock only MOVED the window: a run could still start
    # between the check and the write. The whole body holds the lock instead, so
    # run_parser cannot take it and set _running while the .env is being rewritten.
    a = _api(tmp_path)
    held = {}
    from topicparser import settings
    monkeypatch.setattr(settings, "write_env",
                        lambda *args, **kw: held.update(locked=a._run_lock.locked()))
    monkeypatch.setattr(a, "_env_path", lambda: str(tmp_path / ".env"))
    a.save_tuning({"SCORE_THRESHOLD": 80})
    assert held["locked"] is True


def test_the_wipe_happens_under_the_run_lock(tmp_path, monkeypatch):
    a = _api(tmp_path)
    held = {}
    monkeypatch.setattr(api_mod.store, "reset_all",
                        lambda **kw: held.update(locked=a._run_lock.locked()) or "b.db")
    a.reset_database({"topics": True})
    assert held["locked"] is True
