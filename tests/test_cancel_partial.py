"""Stop must not swallow what the run already finished.

A run is expensive: minutes of scraping plus a paid scoring call per profile. When
the user stops it, the profiles that already finished have been INSERTED into
`shown_topics` and auto-tracked — but the cancel used to return an empty list, so
those topics were never shown, never exportable, and cross-run dedup then suppressed
them on the next run as "already shown". Paid for, then silently thrown away.
"""
import json
import threading

import pytest

from topicparser import store
from topicparser import i18n
from topicparser.api import Api
from topicparser.models import Signal
from topicparser.pipeline import run, RunCancelled

FRESH = "2999-01-01T00:00:00Z"     # always inside the freshness window


class TrippingCollector:
    """Collects one signal per profile; trips Stop while collecting the SECOND one,
    exactly as pressing the button mid-scrape would."""
    source = "github"

    def __init__(self, event, stop_on="B"):
        self.event, self.stop_on = event, stop_on

    def collect(self, name, cfg):
        if name == self.stop_on:
            self.event.set()
        return [Signal.make(source="github", title=f"own/{name}", description="d",
                            url=f"https://github.com/own/{name}", date=FRESH,
                            profile=name, stars=10)]


class Client:
    def make(self, messages):
        return json.dumps({"scored": [{"i": 0, "score": 90, "title": "T",
                                       "reason": "чому це цікаво"}],
                           "groups": [], "stale": [], "drop": []})


def _cancel_after_first_profile(tmp_path, **kw):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    event = threading.Event()
    with pytest.raises(RunCancelled) as ei:
        run(selected=["A", "B"], profiles={"A": {}, "B": {}},
            collectors=[TrippingCollector(event)], client=Client(),
            threshold=70, x_days=3, gh_days=60, cancel_event=event,
            # a prompt, or the run warns (rightly) that it is scoring on the stub —
            # this fixture is about cancellation, not about the rules
            prompt_loader=lambda name: "SCORE THINGS", **kw)
    return ei.value


def test_cancel_carries_the_finished_profiles_topics(tmp_path):
    err = _cancel_after_first_profile(tmp_path)
    assert [t["title"] for t in err.topics] == ["T"]
    assert err.topics[0]["id"] is not None          # the row the pipeline persisted
    # and it really is in the DB, so the two views agree
    assert [t["title"] for t in store.get_recent_topics(days=60)] == ["T"]


def test_cancel_carries_alerts_and_warnings(tmp_path):
    err = _cancel_after_first_profile(tmp_path)
    assert err.alerts == []          # no trending in this fixture, but the shape is there
    assert err.warnings == []


def test_cancel_writes_the_debug_log_for_what_was_scored(tmp_path):
    # the scoring calls were paid for; their per-signal scores are the only record
    debug = tmp_path / "debug"
    _cancel_after_first_profile(tmp_path, debug_dir=str(debug))
    files = list(debug.glob("run-*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["profiles"]["A"]["topics"], "the finished profile's work is in the log"


def test_cancel_with_nothing_finished_still_reports_empty(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    event = threading.Event(); event.set()
    with pytest.raises(RunCancelled) as ei:
        run(selected=["A"], profiles={"A": {}}, collectors=[TrippingCollector(event)],
            client=Client(), threshold=70, x_days=3, gh_days=60, cancel_event=event)
    assert ei.value.topics == []


def test_api_returns_the_partial_topics_to_the_ui(tmp_path, monkeypatch):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    api = Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
              threshold=70, x_days=3, gh_days=60)
    partial = [{"id": 7, "title": "T", "why": "чому", "links": ["u"], "score": 90}]

    def cancelled(**kw):
        raise RunCancelled(topics=partial, alerts=[{"repo": "a/b"}], warnings=["w"])
    monkeypatch.setattr("topicparser.api.run", cancelled)

    res = api.run_parser({"AI": {"github": {"topics": ["mcp"]}}})
    assert res["cancelled"] is True
    assert res["topics"] == partial
    assert res["alerts"] == [{"repo": "a/b"}]
    assert res["warnings"] == ["w"]
    # the .md scope is this run's ids, or the export would write the PREVIOUS run
    assert api._last_topic_ids == {7}


def test_a_refused_run_sends_no_notification(tmp_path, monkeypatch):
    """No sources selected means nothing ran — a desktop banner saying the run
    finished is a lie, and the run-finished banner is how the owner knows to come
    back to the window."""
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    sent = []
    monkeypatch.setattr("topicparser.api.notify.send",
                        lambda title, msg, **kw: sent.append((title, msg)))
    api = Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
              threshold=70, x_days=3, gh_days=60)
    empty = {"github": {"topics": []}, "x": {"accounts": [], "lists": [], "searches": []}}

    refused = {"error": i18n.t("err.no_sources_selected")}
    assert api.run_parser({"AI": empty}) == refused
    assert api.run_parser({}) == refused
    assert sent == []


def test_a_real_run_still_notifies(tmp_path, monkeypatch):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    sent = []
    monkeypatch.setattr("topicparser.api.notify.send",
                        lambda title, msg, **kw: sent.append((title, msg)))
    monkeypatch.setattr("topicparser.api.run",
                        lambda **kw: {"topics": [], "alerts": [], "warnings": []})
    api = Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
              threshold=70, x_days=3, gh_days=60)
    api.run_parser({"AI": {"github": {"topics": ["mcp"]}}})
    assert len(sent) == 1
