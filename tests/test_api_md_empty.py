"""Exporting with nothing to export.

The .md button used to be live from the moment the app opened, so pressing it
before any run wrote a file holding a header and no topics. The UI keeps it
disabled now; this is the backend half of the same guard, so a stale window or a
direct call cannot produce that file either.
"""
from topicparser.api import Api


def _api(**kw):
    return Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
               threshold=70, x_days=3, gh_days=60, **kw)


def test_save_md_refuses_when_the_last_run_kept_nothing(tmp_path, monkeypatch):
    api = _api()
    monkeypatch.setattr(api, "_md_topics", lambda: [])
    path = tmp_path / "t.md"

    res = api.save_md(str(path))

    assert res == {"ok": False, "empty": True}
    assert not path.exists()


def test_save_md_does_not_open_the_save_dialog_with_nothing_to_write(monkeypatch):
    """The refusal comes BEFORE the file picker — asking where to put an empty
    file and only then refusing would be worse than not asking at all."""
    api = _api()
    monkeypatch.setattr(api, "_md_topics", lambda: [])
    asked = []
    monkeypatch.setattr(api, "_ask_save_path", lambda: asked.append(1) or "/tmp/x.md")

    res = api.save_md()

    assert res == {"ok": False, "empty": True}
    assert asked == []


def test_save_md_still_writes_when_there_is_something_kept(tmp_path, monkeypatch):
    api = _api()
    monkeypatch.setattr(api, "_md_topics", lambda: [
        {"title": "T", "why": "W", "score": 80,
         "links": ["https://github.com/x/y"], "kept": 1}])
    path = tmp_path / "t.md"

    assert api.save_md(str(path))["ok"]
    assert "T" in path.read_text(encoding="utf-8")
