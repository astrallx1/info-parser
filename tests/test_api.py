import topicparser.store as store
from topicparser import i18n
from topicparser.api import Api
from topicparser.pipeline import RunCancelled

def test_get_profiles_and_run(tmp_path, monkeypatch):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    api = Api(profiles={"profiles": {"AI": {"github": {"topics": ["mcp"]}}}},
              build_collectors=lambda: [], build_client=lambda: None,
              threshold=80, x_days=3, gh_days=21)
    assert list(api.get_profiles()["profiles"].keys()) == ["AI"]

    monkeypatch.setattr("topicparser.api.run",
                        lambda **kw: [{"id": 1, "title": "T", "why": "W",
                                       "score": 90, "links": ["u1"]}])
    res = api.run_parser({"AI": {"github": {"topics": ["mcp"]}}})
    assert res[0]["title"] == "T"


def test_run_parser_prunes_profiles_without_selected_sources(tmp_path, monkeypatch):
    # selection carries only the checked sources per profile; a profile with
    # nothing checked must be dropped, and run() gets exactly the pruned config
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    api = Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
              threshold=80, x_days=5, gh_days=21)
    captured = {}
    monkeypatch.setattr("topicparser.api.run", lambda **kw: captured.update(kw) or [])
    selection = {
        "AI": {"github": {"topics": ["mcp"]},
               "x": {"accounts": ["OpenAI"], "lists": [], "searches": []}},
        "Crypto": {"x": {"accounts": [], "lists": [], "searches": []}},
    }
    api.run_parser(selection)
    assert captured["selected"] == ["AI"]                       # Crypto pruned
    assert captured["profiles"] == {"AI": selection["AI"]}      # only chosen sources reach run()


def test_run_parser_errors_when_nothing_selected(tmp_path, monkeypatch):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    api = Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
              threshold=80, x_days=5, gh_days=21)
    called = []
    monkeypatch.setattr("topicparser.api.run", lambda **kw: called.append(1) or [])
    res = api.run_parser({"AI": {"x": {"accounts": [], "lists": [], "searches": []}}})
    assert res == {"error": i18n.t("err.no_sources_selected")}
    assert called == []

def test_run_parser_returns_cancelled_shape_when_stopped(tmp_path, monkeypatch):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    api = Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
              threshold=80, x_days=3, gh_days=21)
    monkeypatch.setattr("topicparser.api.run", lambda **kw: (_ for _ in ()).throw(RunCancelled()))
    res = api.run_parser({"AI": {"github": {"topics": ["mcp"]}}})
    assert res == {"cancelled": True, "topics": [], "alerts": [], "warnings": []}
    assert api._running is False   # cleared even though the run raised


def test_stop_sets_cancel_event_passed_into_run(tmp_path, monkeypatch):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    api = Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
              threshold=80, x_days=3, gh_days=21)
    captured = {}
    def fake_run(**kw):
        captured["cancel_event"] = kw.get("cancel_event")
        return {"topics": [], "alerts": [], "warnings": []}
    monkeypatch.setattr("topicparser.api.run", fake_run)
    api.stop()   # calling stop before any run just pre-arms the event; harmless
    api.run_parser({"AI": {"github": {"topics": ["mcp"]}}})
    assert captured["cancel_event"] is not None
    assert hasattr(captured["cancel_event"], "is_set")


def test_run_parser_resets_cancel_event_on_new_run(tmp_path, monkeypatch):
    # a Stop from a previous run must not immediately cancel the next one
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    api = Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
              threshold=80, x_days=3, gh_days=21)
    monkeypatch.setattr("topicparser.api.run", lambda **kw: (_ for _ in ()).throw(RunCancelled()))
    api.run_parser({"AI": {"github": {"topics": ["mcp"]}}})   # cancels, event ends up set

    captured = {}
    def fake_run(**kw):
        captured["was_set"] = kw["cancel_event"].is_set()
        return {"topics": [], "alerts": [], "warnings": []}
    monkeypatch.setattr("topicparser.api.run", fake_run)
    api.run_parser({"AI": {"github": {"topics": ["mcp"]}}})
    assert captured["was_set"] is False


def test_is_running_reflects_run_state(tmp_path, monkeypatch):
    # the close-warning hook in main.py asks the api whether a run is in flight
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    api = Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
              threshold=80, x_days=3, gh_days=21)
    assert api.is_running() is False           # idle before any run
    seen = {}
    def fake_run(**kw):
        seen["running_mid"] = api.is_running()  # True while run() executes
        return {"topics": [], "alerts": [], "warnings": []}
    monkeypatch.setattr("topicparser.api.run", fake_run)
    api.run_parser({"AI": {"github": {"topics": ["mcp"]}}})
    assert seen["running_mid"] is True
    assert api.is_running() is False           # cleared after the run returns


def test_phase_reflects_progress_and_resets(tmp_path, monkeypatch):
    # the UI pulls get_phase() on a timer; the pipeline's progress callback feeds it
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    api = Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
              threshold=80, x_days=3, gh_days=21)
    assert api.get_phase() == ""
    captured = {}
    def fake_run(**kw):
        kw["progress"]("Збираю Twitter…")     # pipeline emits a coarse phase
        captured["mid"] = api.get_phase()
        return {"topics": [], "alerts": [], "warnings": []}
    monkeypatch.setattr("topicparser.api.run", fake_run)
    api.run_parser({"AI": {"github": {"topics": ["mcp"]}}})
    assert captured["mid"] == "Збираю Twitter…"   # progress -> phase
    assert api.get_phase() == ""                  # reset once the run ends


def test_set_kept_toggles(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    tid = store.insert_topic(title="T", why="w", links=[], signature="s",
                             score=90, profile="AI")
    api = Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
              threshold=80, x_days=3, gh_days=21)
    api.set_kept(tid, False)
    assert store.get_recent_topics(days=1)[0]["kept"] == 0


def _run_returning(*topics):
    """A stub run() that reports the given topic dicts as the last run's output."""
    return lambda **kw: {"topics": list(topics), "alerts": [], "warnings": []}


def test_export_md_only_last_run_topics(tmp_path, monkeypatch):
    # one run = one .md: the export carries ONLY the topics from the most recent
    # run, not older topics still sitting in the DB from previous runs
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    # rows carry the run that wrote them, the way pipeline stamps them, so "the last
    # run" is a fact in the DB and not a guess from a freshness window
    store.insert_topic(title="OLD", why="w", links=["u_old"], signature="s",
                       score=90, profile="AI", run_id="r1")
    new = store.insert_topic(title="NEW", why="w", links=["u_new"], signature="s",
                             score=90, profile="AI", run_id="r2")
    api = Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
              threshold=80, x_days=5, gh_days=60)
    monkeypatch.setattr("topicparser.api.run",
        _run_returning({"id": new, "title": "NEW", "why": "w",
                        "links": ["u_new"], "score": 90, "profile": "AI"}))
    api.run_parser({"AI": {"github": {"topics": ["mcp"]}}})
    out = str(tmp_path / "out.md")
    api.save_md(out)
    md = (tmp_path / "out.md").read_text(encoding="utf-8")
    assert "NEW" in md
    assert "OLD" not in md


def test_export_md_empty_before_any_run(tmp_path):
    # nothing has run this session -> nothing to export, even if the DB has topics
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    store.insert_topic(title="OLD", why="w", links=["u"], signature="s",
                       score=90, profile="AI")
    api = Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
              threshold=80, x_days=5, gh_days=60)
    out = str(tmp_path / "out.md")
    # it used to write a file holding the header and no topics; now it refuses outright
    assert api.save_md(out) == {"ok": False, "empty": True}
    assert not (tmp_path / "out.md").exists()


def test_save_md_only_last_run_topics(tmp_path, monkeypatch):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    # rows carry the run that wrote them, the way pipeline stamps them, so "the last
    # run" is a fact in the DB and not a guess from a freshness window
    store.insert_topic(title="OLD", why="w", links=["u_old"], signature="s",
                       score=90, profile="AI", run_id="r1")
    new = store.insert_topic(title="NEW", why="w", links=["u_new"], signature="s",
                             score=90, profile="AI", run_id="r2")
    api = Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
              threshold=80, x_days=5, gh_days=60)
    monkeypatch.setattr("topicparser.api.run",
        _run_returning({"id": new, "title": "NEW", "why": "w",
                        "links": ["u_new"], "score": 90, "profile": "AI"}))
    api.run_parser({"AI": {"github": {"topics": ["mcp"]}}})
    out = tmp_path / "topics.md"
    res = api.save_md(path=str(out))
    assert res["ok"] is True
    text = out.read_text(encoding="utf-8")
    assert "NEW" in text and "OLD" not in text
