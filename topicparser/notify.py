"""Best-effort desktop notification when a run finishes.

A run takes minutes (the X scrape is most of it) and the owner does not watch the
window, so the banner is the only signal it is done. macOS goes through the built-in
`osascript`; Windows prefers `winotify` and falls back to a PowerShell toast when the
package is missing, so the feature degrades instead of disappearing. Never raises — a
notification failure must not affect the run result."""
import os
import platform
import uuid
import shutil
import subprocess
import threading

from topicparser import paths

# A toast needs an AppUserModelID registered in the Start menu or Windows silently
# drops it. PowerShell's own is always present, so the fallback borrows it.
_PS_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"


def _winotify_toast():
    """The winotify Notification class, or None when the package is not installed.
    A seam, so the PowerShell fallback is testable without uninstalling anything."""
    try:
        from winotify import Notification
        return Notification
    except ImportError:
        return None


def _mac_bundle_id():
    """The running process's bundle identifier, or None when there is no bundle.

    Running from source there is none, and posting a user notification on behalf of no
    bundle is what the framework refuses to do. Never raises: this is called on the way
    to a best-effort banner."""
    try:
        from Foundation import NSBundle
        return NSBundle.mainBundle().bundleIdentifier()
    except Exception:
        return None


def _import_user_notifications():
    """A seam, so the failure path is testable without uninstalling pyobjc."""
    import UserNotifications
    return UserNotifications


def _post_user_notification(title: str, message: str) -> bool:
    """Post through UserNotifications, from INSIDE the app process.

    This is the only way the banner carries the app's own icon: `osascript` is a
    separate process, so the system shows Script Editor's icon and AppleScript cannot
    set one. Requires a bundle (see `_mac_bundle_id`) and asks for permission once, in
    the app's own name. Returns False on any problem so the caller can fall back."""
    try:
        un = _import_user_notifications()
        center = un.UNUserNotificationCenter.currentNotificationCenter()
        # alert + sound. The GRANT is what decides: macOS refuses an app it does not
        # trust ("Notifications are not allowed for this application", measured on an
        # ad-hoc signed PyInstaller build) and then still answers the POST with
        # error=None, so posting blind reports success while nothing is shown.
        granted, done = [], threading.Event()

        def auth(ok, error):
            granted.append(bool(ok))
            done.set()

        center.requestAuthorizationWithOptions_completionHandler_((1 << 2) | (1 << 0), auth)
        if not done.wait(3) or not (granted and granted[0]):
            return False
        content = un.UNMutableNotificationContent.alloc().init()
        content.setTitle_(title)
        content.setBody_(message)
        content.setSound_(un.UNNotificationSound.defaultSound())
        request = un.UNNotificationRequest.requestWithIdentifier_content_trigger_(
            str(uuid.uuid4()), content, None)
        # The post is asynchronous, so a REFUSED notification (permission denied,
        # unsigned bundle) would otherwise look like a success and the run would end
        # with no banner at all. Wait briefly for the completion handler: an error means
        # fall back to osascript, a timeout means assume it landed.
        done, failed = threading.Event(), []

        def handler(error):
            if error is not None:
                failed.append(error)
            done.set()

        center.addNotificationRequest_withCompletionHandler_(request, handler)
        done.wait(1.5)
        return not failed
    except Exception:
        return False


def _post_legacy_notification(title: str, message: str) -> bool:
    """`NSUserNotification`: deprecated since macOS 11, and the only path that actually
    delivers from an UNSIGNED bundle — verified on this machine, banner and all.

    `UserNotifications` is the supported API and refuses an ad-hoc signed app outright;
    this old one asks nobody's permission. Apple can remove it in any release, which is
    why it sits BETWEEN the modern path and osascript rather than replacing either."""
    try:
        from Foundation import NSUserNotification, NSUserNotificationCenter
        center = NSUserNotificationCenter.defaultUserNotificationCenter()
        if center is None:                 # removed, or no bundle to post as
            return False
        note = NSUserNotification.alloc().init()
        note.setTitle_(title)
        note.setInformativeText_(message)
        center.deliverNotification_(note)
        return True
    except Exception:
        return False


def _send_mac(title: str, message: str, sound: str) -> bool:
    """Three paths, best icon first. Only a BUNDLE can post as the app at all; from
    source there is nobody to post as and osascript is the whole story."""
    if _mac_bundle_id():
        # signed build: the supported API, which needs a permission macOS grants
        if _post_user_notification(title, message):
            return True
        # unsigned build: the deprecated API still delivers, with the app's own icon
        if _post_legacy_notification(title, message):
            return True
    return _send_mac_osascript(title, message, sound)


def _send_mac_osascript(title: str, message: str, sound: str) -> bool:
    osa = shutil.which("osascript")
    if not osa:
        return False
    # osascript's AppleScript string literals use double quotes — neutralize them.
    # The BACKSLASH goes first and stays a backslash: it is AppleScript's own escape,
    # so a Windows path or a regex inside an error message would end the literal early
    # and the notification would just never appear.
    def _lit(t):
        return t.replace("\\", "\\\\").replace('"', "'")
    ttl, msg = _lit(title), _lit(message)
    script = f'display notification "{msg}" with title "{ttl}" sound name "{sound}"'
    subprocess.run([osa, "-e", script], check=False, timeout=5,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def _toast_icon() -> str:
    """The app's own logo for a Windows toast, or "" when it is not shipped.

    winotify wants an ABSOLUTE path to an image and silently shows nothing in its place
    otherwise. macOS needs no equivalent, but not for the reason this comment used to
    give: `osascript` cannot set an icon, and the banner carries the icon of the process
    that SENT it — Script Editor, not the app. That is why the packaged build posts
    through UserNotifications instead, which takes the icon from the bundle.
    """
    icon = os.path.join(paths.bundle_dir(), "assets", "icons", "notify.png")
    return icon if os.path.exists(icon) else ""


def _send_windows(title: str, message: str) -> bool:
    toast_cls = _winotify_toast()
    if toast_cls is not None:
        toast = toast_cls(app_id="Info Parser", title=title, msg=message,
                          icon=_toast_icon())
        try:
            from winotify import audio
            toast.set_audio(audio.Default, loop=False)
        except Exception:
            pass                      # audio is optional; a silent toast still lands
        toast.show()
        return True

    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return False
    ttl, msg = title.replace("'", "''"), message.replace("'", "''")   # PS literal escape
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,"
        " ContentType=WindowsRuntime] > $null;"
        "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        "$n=$t.GetElementsByTagName('text');"
        f"$n[0].AppendChild($t.CreateTextNode('{ttl}')) > $null;"
        f"$n[1].AppendChild($t.CreateTextNode('{msg}')) > $null;"
        "$toast=[Windows.UI.Notifications.ToastNotification]::new($t);"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        f"'{_PS_APP_ID}').Show($toast)"
    )
    subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", script],
                   check=False, timeout=10,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def send(title: str, message: str, sound: str = "Glass") -> bool:
    """Show a desktop notification. True if one was dispatched, False on any
    unsupported-OS / missing-tool / failure path. Never raises."""
    try:
        system = platform.system()
        if system == "Darwin":
            return _send_mac(title or "", message or "", sound)
        if system == "Windows":
            return _send_windows(title or "", message or "")
        return False
    except Exception:
        return False
