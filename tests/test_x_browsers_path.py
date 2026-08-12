"""A frozen build must still find the Chromium installed on the machine.

playwright's own `_transport.connect` does `env.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")`
whenever `sys.frozen` is set, and "0" means "browsers live inside the package". Nothing
installs them there, so the packaged app looked for Chromium inside its own bundle and
every X collection died with `Executable doesn't exist at .../.local-browsers/...`.
`setdefault` is the seam: an explicitly set variable wins.
"""
import os
import sys

import pytest

from topicparser.collectors import x as xmod


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    return monkeypatch


def test_frozen_run_points_playwright_at_the_user_browser_cache(clean_env, tmp_path):
    clean_env.setattr(xmod.paths, "is_frozen", lambda: True)
    clean_env.setattr(sys, "platform", "darwin")
    # BOTH: `expanduser` reads USERPROFILE on Windows and ignores HOME, so a
    # hardcoded home made this pass on the Mac and fail on the CI runner
    clean_env.setenv("HOME", str(tmp_path))
    clean_env.setenv("USERPROFILE", str(tmp_path))

    xmod.use_installed_browsers()

    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == \
        os.path.join(str(tmp_path), "Library", "Caches", "ms-playwright")


def test_windows_cache_follows_localappdata(clean_env):
    clean_env.setattr(xmod.paths, "is_frozen", lambda: True)
    clean_env.setattr(sys, "platform", "win32")
    clean_env.setenv("LOCALAPPDATA", r"C:\Users\tester\AppData\Local")

    xmod.use_installed_browsers()

    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == \
        os.path.join(r"C:\Users\tester\AppData\Local", "ms-playwright")


def test_an_explicit_setting_is_never_overridden(clean_env):
    """Someone who bundles browsers on purpose sets this to 0 — respect it."""
    clean_env.setattr(xmod.paths, "is_frozen", lambda: True)
    clean_env.setenv("PLAYWRIGHT_BROWSERS_PATH", "0")

    xmod.use_installed_browsers()

    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == "0"


def test_running_from_source_is_left_alone(clean_env):
    """Unfrozen playwright already defaults to the same cache — don't touch it."""
    clean_env.setattr(xmod.paths, "is_frozen", lambda: False)

    xmod.use_installed_browsers()

    assert "PLAYWRIGHT_BROWSERS_PATH" not in os.environ


def test_the_session_sets_it_before_playwright_starts(clean_env, tmp_path, monkeypatch):
    """The fix is worthless unless it runs before the driver is spawned."""
    clean_env.setattr(xmod.paths, "is_frozen", lambda: True)
    clean_env.setattr(sys, "platform", "darwin")
    clean_env.setenv("HOME", str(tmp_path))
    clean_env.setenv("USERPROFILE", str(tmp_path))
    cookies = tmp_path / "cookies.json"
    cookies.write_text("{}", encoding="utf-8")

    seen = {}

    class _BoomPlaywright:
        def start(self):
            seen["at_start"] = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
            raise RuntimeError("stop here — the env var is what we came for")

    monkeypatch.setitem(sys.modules, "playwright.sync_api",
                        type(sys)("playwright.sync_api"))
    sys.modules["playwright.sync_api"].sync_playwright = lambda: _BoomPlaywright()

    session = xmod._PlaywrightSession(str(cookies), limit=1, max_scrolls=1)
    with pytest.raises(RuntimeError):
        session.__enter__()

    assert seen["at_start"] == os.path.join(str(tmp_path), "Library", "Caches",
                                            "ms-playwright")
