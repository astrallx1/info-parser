"""Runtime files are addressed relative to the APP, never to the current directory.

Run from source the two are the same, so nothing changes. Packaged they are not:
a `.exe` started from a Start-menu shortcut gets whatever CWD Windows feels like,
and `./topics.db` would then be a brand-new empty database somewhere else, with
`cookies.json` and `profiles.yaml` nowhere to be found.

A PACKAGED build keeps them in the platform's user-data folder instead of beside the
executable. That is not tidiness: a downloaded `.app` is quarantined, and macOS then
runs it through App Translocation from a randomised READ-ONLY path, so "beside the
executable" is a throwaway temp directory the database disappears from. Writing next
to an app in `/Applications` or `C:\\Program Files` is wrong for the same reason.
Running from source is untouched — that is where the repo's own committed `.env`,
`profiles.yaml` and `topics.db` live.
"""
import os
import sys
from topicparser import paths


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_app_dir_is_the_project_root_when_running_from_source():
    assert paths.app_dir() == PROJECT_ROOT


def test_resolve_leaves_an_absolute_path_alone():
    # a bare leading separator is NOT an absolute path on Windows (and since Python
    # 3.13 `ntpath.isabs` says so), so the case has to be spelled per platform
    abs_path = ("D:\\elsewhere\\topics.db" if sys.platform == "win32"
                else os.path.join(os.sep, "tmp", "elsewhere", "topics.db"))
    assert os.path.isabs(abs_path)
    assert paths.resolve(abs_path) == abs_path


def test_resolve_anchors_a_relative_path_to_the_app_not_the_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)          # user launched the app from somewhere else
    assert paths.resolve("./topics.db") == os.path.join(PROJECT_ROOT, "topics.db")


def test_resolve_passes_empty_through():
    assert paths.resolve("") == ""


def _frozen(monkeypatch, tmp_path, platform):
    """A frozen build on `platform`, with a clean HOME so nothing real is touched."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)


def test_a_frozen_mac_build_writes_to_application_support(monkeypatch, tmp_path):
    _frozen(monkeypatch, tmp_path, "darwin")
    assert paths.app_dir() == str(
        tmp_path / "Library" / "Application Support" / "Info Parser")


def test_a_frozen_windows_build_writes_to_appdata(monkeypatch, tmp_path):
    _frozen(monkeypatch, tmp_path, "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert paths.app_dir() == str(tmp_path / "Roaming" / "Info Parser")


def test_a_frozen_windows_build_falls_back_when_appdata_is_unset(monkeypatch, tmp_path):
    _frozen(monkeypatch, tmp_path, "win32")
    assert paths.app_dir() == str(
        tmp_path / "AppData" / "Roaming" / "Info Parser")


def test_a_frozen_linux_build_honours_xdg(monkeypatch, tmp_path):
    _frozen(monkeypatch, tmp_path, "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert paths.app_dir() == str(tmp_path / "xdg" / "Info Parser")


def test_the_data_folder_is_created_on_demand(monkeypatch, tmp_path):
    _frozen(monkeypatch, tmp_path, "darwin")
    where = paths.app_dir()
    assert os.path.isdir(where)


def test_a_read_only_home_does_not_take_the_app_down(monkeypatch, tmp_path):
    """`app_dir()` is called during import of config/store/i18n. It must return a path
    rather than raise, whatever the filesystem says."""
    _frozen(monkeypatch, tmp_path, "darwin")

    def refuse(*a, **kw):
        raise PermissionError("read-only")

    monkeypatch.setattr(paths.os, "makedirs", refuse)
    assert paths.app_dir().endswith("Info Parser")


def test_running_from_source_is_untouched_by_all_of_that():
    # the repo's own committed .env / profiles.yaml / topics.db keep working
    assert paths.app_dir() == PROJECT_ROOT


def test_bundle_dir_is_meipass_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert paths.bundle_dir() == str(tmp_path)


def test_bundle_dir_is_the_project_root_from_source():
    assert paths.bundle_dir() == PROJECT_ROOT
