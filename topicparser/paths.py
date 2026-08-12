"""Where the app's files live, whether it runs from source or from a bundle.

Everything the owner edits or the app writes (`.env`, `profiles.yaml`,
`cookies.json`, `topics.db`, `debug/`, the tuning prompts) is addressed relative to
the APP, never to the current working directory. From source the two coincide, so
nothing changes; packaged they do not — a `.exe` launched from a Start-menu shortcut
inherits an arbitrary CWD, and `./topics.db` would quietly become a fresh empty
database in some other folder while `cookies.json` went missing.

A PACKAGED build keeps them in the platform's user-data folder rather than beside the
executable. That is not tidiness:

* a downloaded `.app` carries `com.apple.quarantine`, and macOS then runs it through
  App Translocation from a randomised READ-ONLY path — so "beside the executable" is
  a throwaway temp directory, and the database, the keys and the X session vanish
  with it on the next launch;
* an app in `/Applications` or `C:\\Program Files` cannot write next to itself either;
* replacing the bundle no longer risks taking the data with it.

Running from SOURCE is deliberately untouched — that is where this repo's own
committed `.env`, `profiles.yaml` and `topics.db` live, and the whole dev workflow
depends on them being found there.
"""
import os
import sys

_PKG_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

APP_NAME = "Info Parser"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _user_data_root() -> str:
    """The platform's own place for per-user application data."""
    if sys.platform == "win32":
        return os.environ.get("APPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Roaming")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    return os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share")


def app_dir() -> str:
    """The folder the runtime files sit in: the platform's user-data folder when
    packaged, the project root when running from source."""
    if not is_frozen():
        return _PKG_PARENT
    d = os.path.join(_user_data_root(), APP_NAME)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        # `app_dir()` is called while config/store/i18n are still importing. It has to
        # hand back a path rather than raise, whatever the filesystem says.
        pass
    return d


def bundle_dir() -> str:
    """Read-only files shipped INSIDE the build (PyInstaller unpacks them to
    `sys._MEIPASS`); the project root when running from source."""
    if is_frozen():
        return getattr(sys, "_MEIPASS", None) or app_dir()
    return _PKG_PARENT


def resolve(path: str) -> str:
    """Anchor a relative runtime path to `app_dir()` instead of the CWD. Absolute
    paths (and an empty one) pass through untouched, so `DB_PATH=D:\\parser\\x.db`
    in `.env` still means exactly that."""
    if not path:
        return path
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(app_dir(), path))
