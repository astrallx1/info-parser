import topicparser.store as store
from topicparser.api import Api


def _api():
    return Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
               threshold=80, x_days=3, gh_days=21)


def test_get_tracked_returns_detail(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    store.add_tracked_repo("foo/bar")
    store.record_stars("foo/bar", 10)

    rows = _api().get_tracked()

    assert len(rows) == 1
    assert rows[0]["repo"] == "foo/bar"
    assert rows[0]["stars"] == 10
    assert rows[0]["velocity"] is None       # only one measurement


def test_unwatch_repo_removes(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    store.add_tracked_repo("foo/bar")

    _api().unwatch_repo("foo/bar")

    assert store.get_tracked_repos() == []


def test_save_md_writes_only_kept_topics(tmp_path, monkeypatch):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    keep = store.insert_topic(title="Keep — me", why="w", links=["u1"],
                              signature="s", score=90, profile="AI", run_id="r1")
    drop = store.insert_topic(title="Drop me", why="w", links=["u2"],
                              signature="s", score=90, profile="AI", run_id="r1")
    api = _api()
    # both topics belong to the most recent run (one run = one .md scope);
    # then one gets un-kept and must fall out of the export
    monkeypatch.setattr("topicparser.api.run", lambda **kw: {
        "topics": [{"id": keep, "title": "Keep — me", "why": "w",
                    "links": ["u1"], "score": 90, "profile": "AI"},
                   {"id": drop, "title": "Drop me", "why": "w",
                    "links": ["u2"], "score": 90, "profile": "AI"}],
        "alerts": [], "warnings": []})
    api.run_parser({"AI": {"github": {"topics": ["mcp"]}}})
    store.set_kept(drop, False)

    out = tmp_path / "out.md"
    res = api.save_md(path=str(out))

    assert res["ok"] is True
    text = out.read_text(encoding="utf-8")
    assert "Keep — me" in text            # em-dash preserved, kept topic present
    assert "Drop me" not in text          # unkept topic excluded


def test_save_md_cancelled_returns_not_ok(tmp_path, monkeypatch):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    api = _api()
    monkeypatch.setattr(api, "_ask_save_path", lambda: None)   # user cancels dialog

    res = api.save_md()

    assert res["ok"] is False
