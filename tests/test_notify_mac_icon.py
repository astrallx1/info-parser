"""The macOS banner has to carry the app's own icon.

`osascript` is a separate process, so the system shows ITS icon (Script Editor) and
there is no way to set one from AppleScript. The only way to get the app's own logo is
to post the notification from inside the app process through UserNotifications, which
needs a real bundle: from source there is none, so the osascript path stays as the
fallback.
"""
import sys

import pytest

from topicparser import notify


@pytest.fixture(autouse=True)
def _mac(monkeypatch):
    monkeypatch.setattr(notify.platform, "system", lambda: "Darwin")


def test_a_bundled_app_posts_through_usernotifications(monkeypatch):
    posted = {}
    monkeypatch.setattr(notify, "_mac_bundle_id", lambda: "com.astrallx.infoparser")
    monkeypatch.setattr(notify, "_post_user_notification",
                        lambda title, message: posted.update(t=title, m=message) or True)
    monkeypatch.setattr(notify, "_send_mac_osascript",
                        lambda *a: pytest.fail("osascript used inside a bundle"))

    assert notify.send("Info Parser", "5 topics ready") is True
    assert posted == {"t": "Info Parser", "m": "5 topics ready"}


def test_running_from_source_still_uses_osascript(monkeypatch):
    """No bundle id means no bundle: the framework call would be posting on behalf of
    nobody, so the old path has to stay."""
    used = {}
    monkeypatch.setattr(notify, "_mac_bundle_id", lambda: None)
    monkeypatch.setattr(notify, "_post_user_notification",
                        lambda *a: pytest.fail("framework used without a bundle"))
    monkeypatch.setattr(notify, "_send_mac_osascript",
                        lambda title, message, sound: used.update(t=title) or True)

    assert notify.send("Info Parser", "done") is True
    assert used["t"] == "Info Parser"


def test_a_framework_failure_falls_back_rather_than_going_silent(monkeypatch):
    used = {}
    monkeypatch.setattr(notify, "_mac_bundle_id", lambda: "com.astrallx.infoparser")
    monkeypatch.setattr(notify, "_post_user_notification", lambda *a: False)
    # the legacy path too, or the fallback under test is never reached: on a machine
    # where NSUserNotification still delivers, it answers True and osascript is skipped
    monkeypatch.setattr(notify, "_post_legacy_notification", lambda *a: False)
    monkeypatch.setattr(notify, "_send_mac_osascript",
                        lambda title, message, sound: used.update(t=title) or True)

    assert notify.send("Info Parser", "done") is True
    assert used["t"] == "Info Parser", "a dead framework must not lose the banner"


def test_the_framework_path_never_raises(monkeypatch):
    """It reaches into pyobjc; anything there must degrade, never take the run down."""
    monkeypatch.setattr(notify, "_import_user_notifications",
                        lambda: (_ for _ in ()).throw(RuntimeError("no framework")))

    assert notify._post_user_notification("T", "M") is False


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_the_bundle_id_helper_never_claims_to_be_the_app():
    """Running the suite is not running the app, so it must not answer with the APP's
    id — that is what decides whether the notification may be posted as Info Parser.

    It is NOT asserted to be None: a framework Python (python.org, and the GitHub
    macOS runner) has a bundle of its own and honestly reports `org.python.python`,
    while the `uv` interpreter used for development has none. Either answer is true;
    only the app's own id would be a lie."""
    assert notify._mac_bundle_id() != "com.astrallx.infoparser"


def test_a_refused_post_reports_failure_so_the_caller_can_fall_back(monkeypatch):
    """The post is async: a denied permission answers through the completion handler,
    and without reading it a refused banner looked exactly like a delivered one."""
    class _Center:
        def requestAuthorizationWithOptions_completionHandler_(self, opts, cb):
            pass

        def addNotificationRequest_withCompletionHandler_(self, req, cb):
            cb("denied")                      # the framework hands back an NSError

    class _Fake:
        UNUserNotificationCenter = type("C", (), {"currentNotificationCenter": staticmethod(lambda: _Center())})
        UNMutableNotificationContent = type("M", (), {
            "alloc": staticmethod(lambda: type("I", (), {
                "init": staticmethod(lambda: type("O", (), {
                    "setTitle_": lambda self, v: None, "setBody_": lambda self, v: None,
                    "setSound_": lambda self, v: None})())})())})
        UNNotificationSound = type("S", (), {"defaultSound": staticmethod(lambda: None)})
        UNNotificationRequest = type("R", (), {
            "requestWithIdentifier_content_trigger_": staticmethod(lambda i, c, t: object())})

    monkeypatch.setattr(notify, "_import_user_notifications", lambda: _Fake)
    assert notify._post_user_notification("T", "M") is False


def test_a_denied_permission_falls_back_instead_of_posting_into_the_void(monkeypatch):
    """macOS refuses an app it does not trust and then answers the POST with no error
    at all, so the grant is the only honest signal. Measured on the real build:
    "Notifications are not allowed for this application", authorizationStatus=denied,
    post error=None, no banner."""
    class _Center:
        def requestAuthorizationWithOptions_completionHandler_(self, opts, cb):
            cb(False, "Notifications are not allowed for this application")

        def addNotificationRequest_withCompletionHandler_(self, req, cb):
            raise AssertionError("must not post without a grant")

    monkeypatch.setattr(notify, "_import_user_notifications",
                        lambda: type("F", (), {"UNUserNotificationCenter": type(
                            "C", (), {"currentNotificationCenter": staticmethod(lambda: _Center())})}))
    assert notify._post_user_notification("T", "M") is False


def test_an_unsigned_bundle_falls_to_the_deprecated_api_before_osascript(monkeypatch):
    """UserNotifications is refused without an Apple signature; NSUserNotification is
    deprecated but delivers, and its banner carries the app's own icon. osascript is
    the last resort because its banner is Script Editor's."""
    order = []
    monkeypatch.setattr(notify, "_mac_bundle_id", lambda: "com.astrallx.infoparser")
    monkeypatch.setattr(notify, "_post_user_notification",
                        lambda *a: order.append("modern") or False)
    monkeypatch.setattr(notify, "_post_legacy_notification",
                        lambda *a: order.append("legacy") or True)
    monkeypatch.setattr(notify, "_send_mac_osascript",
                        lambda *a: order.append("osascript") or True)

    assert notify.send("Info Parser", "done") is True
    assert order == ["modern", "legacy"], "osascript must not run once one lands"


def test_osascript_is_still_the_last_resort(monkeypatch):
    monkeypatch.setattr(notify, "_mac_bundle_id", lambda: "com.astrallx.infoparser")
    monkeypatch.setattr(notify, "_post_user_notification", lambda *a: False)
    monkeypatch.setattr(notify, "_post_legacy_notification", lambda *a: False)
    used = {}
    monkeypatch.setattr(notify, "_send_mac_osascript",
                        lambda t, m, s: used.update(t=t) or True)

    assert notify.send("Info Parser", "done") is True
    assert used["t"] == "Info Parser"


def test_the_deprecated_path_never_raises(monkeypatch):
    """Apple can remove it in any release; that must degrade, not crash a run."""
    import builtins
    real_import = builtins.__import__

    def boom(name, *a, **k):
        if name == "Foundation":
            raise ImportError("gone in macOS 27")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", boom)
    assert notify._post_legacy_notification("T", "M") is False
