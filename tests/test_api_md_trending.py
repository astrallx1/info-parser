from topicparser.api import Api


def _api(**kw):
    return Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
               threshold=70, x_days=3, gh_days=60, **kw)


def test_save_md_carries_the_last_run_alerts(tmp_path, monkeypatch):
    api = _api()
    api._last_alerts = [{"repo": "a/hot", "url": "https://github.com/a/hot",
                         "stars": 900, "velocity": 120.0, "description": "Опис."}]
    monkeypatch.setattr(api, "_md_topics", lambda: [
        {"title": "T", "why": "W", "score": 80,
         "links": ["https://github.com/x/y"], "kept": 1}])
    path = tmp_path / "t.md"
    assert api.save_md(str(path))["ok"]
    text = path.read_text(encoding="utf-8")
    assert "TRENDING" in text and "a/hot" in text and "Опис." in text


def test_alerts_default_to_none_before_any_run(tmp_path, monkeypatch):
    api = _api()
    monkeypatch.setattr(api, "_md_topics", lambda: [
        {"title": "T", "why": "W", "links": ["https://github.com/x/y"], "kept": 1}])
    path = tmp_path / "t.md"
    api.save_md(str(path))
    assert "TRENDING" not in path.read_text(encoding="utf-8")
