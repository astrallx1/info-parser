import topicparser.store as store
from topicparser.api import Api


def _api(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    return Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
               threshold=80, x_days=3, gh_days=21)


def _capture_notify(monkeypatch):
    calls = []
    monkeypatch.setattr("topicparser.api.notify.send",
                        lambda title, message, **kw: calls.append((title, message)))
    return calls


def test_notifies_on_successful_run(tmp_path, monkeypatch):
    api = _api(tmp_path)
    calls = _capture_notify(monkeypatch)
    monkeypatch.setattr("topicparser.api.run",
        lambda **kw: {"topics": [{"id": 1}, {"id": 2}, {"id": 3}],
                      "alerts": [], "warnings": []})
    api.run_parser({"AI": {"github": {"topics": ["mcp"]}}})
    assert len(calls) == 1
    assert "3" in calls[0][1]          # topic count is in the message


def test_notifies_on_cancelled_run(tmp_path, monkeypatch):
    from topicparser.pipeline import RunCancelled
    api = _api(tmp_path)
    calls = _capture_notify(monkeypatch)
    monkeypatch.setattr("topicparser.api.run",
        lambda **kw: (_ for _ in ()).throw(RunCancelled()))
    api.run_parser({"AI": {"github": {"topics": ["mcp"]}}})
    assert len(calls) == 1
    assert "cancel" in calls[0][1].lower()


def test_notify_failure_does_not_break_run(tmp_path, monkeypatch):
    api = _api(tmp_path)
    monkeypatch.setattr("topicparser.api.notify.send",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr("topicparser.api.run",
        lambda **kw: {"topics": [{"id": 1}], "alerts": [], "warnings": []})
    res = api.run_parser({"AI": {"github": {"topics": ["mcp"]}}})
    assert res["topics"] == [{"id": 1}]     # run result survives a notify crash
