"""notify.send dispatches per OS. It was macOS-only (osascript), so on Windows a run
that takes ~15 minutes just ended in silence — the owner does not watch the window."""
import topicparser.notify as notify


def test_unsupported_os_returns_false(monkeypatch):
    monkeypatch.setattr(notify.platform, "system", lambda: "Linux")
    assert notify.send("t", "m") is False


def test_macos_calls_osascript(monkeypatch):
    seen = {}
    # from-source state PINNED, not assumed: a framework Python (python.org, and the
    # GitHub macOS runner) reports a bundle id of its own, and `_send_mac` then tries
    # the two framework paths before osascript. That is correct behaviour and it made
    # these tests depend on which interpreter ran them.
    monkeypatch.setattr(notify, "_mac_bundle_id", lambda: None)
    monkeypatch.setattr(notify.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(notify.shutil, "which", lambda n: "/usr/bin/osascript")
    monkeypatch.setattr(notify.subprocess, "run",
                        lambda cmd, **kw: seen.update(cmd=cmd))
    assert notify.send("Info Parser", "12 тем готово") is True
    assert seen["cmd"][0] == "/usr/bin/osascript"
    assert "12 тем готово" in seen["cmd"][2]


def test_macos_without_osascript_returns_false(monkeypatch):
    # from-source state PINNED, not assumed: a framework Python (python.org, and the
    # GitHub macOS runner) reports a bundle id of its own, and `_send_mac` then tries
    # the two framework paths before osascript. That is correct behaviour and it made
    # these tests depend on which interpreter ran them.
    monkeypatch.setattr(notify, "_mac_bundle_id", lambda: None)
    monkeypatch.setattr(notify.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(notify.shutil, "which", lambda n: None)
    assert notify.send("t", "m") is False


def test_windows_uses_winotify_when_available(monkeypatch):
    shown = {}

    class FakeToast:
        def __init__(self, **kw): shown.update(kw)
        def set_audio(self, *a, **k): shown["audio"] = True
        def show(self): shown["shown"] = True

    monkeypatch.setattr(notify.platform, "system", lambda: "Windows")
    monkeypatch.setattr(notify, "_winotify_toast", lambda: FakeToast)
    assert notify.send("Info Parser", "12 тем готово") is True
    assert shown["title"] == "Info Parser"
    assert shown["msg"] == "12 тем готово"
    assert shown["shown"] is True


def test_windows_falls_back_to_powershell_without_winotify(monkeypatch):
    seen = {}
    monkeypatch.setattr(notify.platform, "system", lambda: "Windows")
    monkeypatch.setattr(notify, "_winotify_toast", lambda: None)   # package not installed
    monkeypatch.setattr(notify.shutil, "which", lambda n: r"C:\powershell.exe")
    monkeypatch.setattr(notify.subprocess, "run", lambda cmd, **kw: seen.update(cmd=cmd))
    assert notify.send("Info Parser", "12 тем") is True
    assert seen["cmd"][0] == r"C:\powershell.exe"
    assert "12 тем" in " ".join(seen["cmd"])


def test_windows_with_nothing_available_returns_false(monkeypatch):
    monkeypatch.setattr(notify.platform, "system", lambda: "Windows")
    monkeypatch.setattr(notify, "_winotify_toast", lambda: None)
    monkeypatch.setattr(notify.shutil, "which", lambda n: None)
    assert notify.send("t", "m") is False


def test_never_raises(monkeypatch):
    # a notification failure must never affect a run's result
    def boom(*a, **k):
        raise RuntimeError("toast subsystem on fire")
    monkeypatch.setattr(notify.platform, "system", lambda: "Windows")
    monkeypatch.setattr(notify, "_winotify_toast", boom)
    assert notify.send("t", "m") is False


def test_quotes_are_neutralised_for_applescript(monkeypatch):
    # osascript string literals use double quotes; an unescaped one breaks the script
    seen = {}
    # from-source state PINNED, not assumed: a framework Python (python.org, and the
    # GitHub macOS runner) reports a bundle id of its own, and `_send_mac` then tries
    # the two framework paths before osascript. That is correct behaviour and it made
    # these tests depend on which interpreter ran them.
    monkeypatch.setattr(notify, "_mac_bundle_id", lambda: None)
    monkeypatch.setattr(notify.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(notify.shutil, "which", lambda n: "/usr/bin/osascript")
    monkeypatch.setattr(notify.subprocess, "run", lambda cmd, **kw: seen.update(cmd=cmd))
    notify.send('say "hi"', 'and "bye"')
    assert '"hi"' not in seen["cmd"][2] and "'hi'" in seen["cmd"][2]


def test_the_windows_toast_carries_the_app_icon(monkeypatch, tmp_path):
    """winotify wants an ABSOLUTE path and shows nothing in its place when the file is
    missing, so it must be the real shipped one — and "" when the build has none."""
    from topicparser import notify, paths

    monkeypatch.setattr(paths, "bundle_dir", lambda: str(tmp_path))
    assert notify._toast_icon() == ""            # nothing shipped -> no broken slot

    icons = tmp_path / "assets" / "icons"
    icons.mkdir(parents=True)
    (icons / "notify.png").write_bytes(b"\x89PNG")
    assert notify._toast_icon() == str(icons / "notify.png")


def test_the_real_build_actually_ships_that_icon():
    """The path above is only worth having if the file is there."""
    import os

    from topicparser import paths

    assert os.path.exists(os.path.join(paths.bundle_dir(), "assets", "icons", "notify.png"))


def test_a_framework_python_still_gets_the_banner_out(monkeypatch):
    """The interpreter having a bundle id of its own must not swallow the banner.

    python.org builds (and the GitHub macOS runner) report `org.python.python`, so
    `_send_mac` tries the two framework paths first. Neither can deliver for an
    interpreter nobody granted permission to, and osascript has to catch it. Three
    tests here silently depended on the DEVELOPMENT interpreter having no bundle at
    all, which is why they passed on this laptop and failed in CI."""
    seen = {}
    monkeypatch.setattr(notify.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(notify, "_mac_bundle_id", lambda: "org.python.python")
    monkeypatch.setattr(notify, "_post_user_notification", lambda *a: False)
    monkeypatch.setattr(notify, "_post_legacy_notification", lambda *a: False)
    monkeypatch.setattr(notify.shutil, "which", lambda n: "/usr/bin/osascript")
    monkeypatch.setattr(notify.subprocess, "run", lambda cmd, **kw: seen.update(cmd=cmd))

    assert notify.send("Info Parser", "done") is True
    assert seen["cmd"][0] == "/usr/bin/osascript"
