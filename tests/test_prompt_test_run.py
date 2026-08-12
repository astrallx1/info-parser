"""Tuning a prompt used to cost a full run: ~15 minutes of scraping plus every paid
call. But each run already saves its raw signals to `debug/`, so a candidate prompt
can be re-scored against them in one call. This is the owner's own offline-replay
method, made available to anyone."""
import json

import pytest

from topicparser import replay


def _debug(tmp_path, name, signals, profile="AI"):
    d = tmp_path / "debug"
    d.mkdir(exist_ok=True)
    (d / name).write_text(json.dumps({
        "time": name, "selected": [profile], "threshold": 70,
        "profiles": {profile: {"collected": len(signals), "after_prefilter": len(signals),
                               "scored": signals, "topics": [], "raw": ""}},
    }, ensure_ascii=False), encoding="utf-8")
    return d


SIGNALS = [
    {"source": "github", "title": "a/one", "url": "https://github.com/a/one",
     "text": "A tool that does a thing.", "score": 45, "reason": "", "kept": None},
    {"source": "x", "title": "@lab", "url": "https://x.com/lab/status/1",
     "text": "We shipped a new model.", "score": 80, "reason": "news", "kept": 1},
]


class FakeClient:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def make(self, messages):
        self.calls.append(messages)
        return self.reply


def test_latest_debug_run_is_the_default_source(tmp_path):
    _debug(tmp_path, "run-20260101-000000.json", SIGNALS)
    _debug(tmp_path, "run-20260807-120000.json", SIGNALS[:1])
    path = replay.latest_debug_run(str(tmp_path / "debug"))
    assert path.endswith("run-20260807-120000.json")


def test_no_debug_run_at_all_reports_it_rather_than_crashing(tmp_path):
    assert replay.latest_debug_run(str(tmp_path / "nothing")) is None


def test_signals_come_back_rebuilt_from_the_log(tmp_path):
    d = _debug(tmp_path, "run-1.json", SIGNALS)
    sigs, before = replay.load_signals(str(d / "run-1.json"), "AI")
    assert [s.title for s in sigs] == ["a/one", "@lab"]
    assert [s.description for s in sigs] == ["A tool that does a thing.",
                                             "We shipped a new model."]
    assert before == [45, 80]


def test_a_profile_missing_from_the_log_falls_back_to_whatever_it_holds(tmp_path):
    d = _debug(tmp_path, "run-1.json", SIGNALS, profile="Crypto")
    sigs, _ = replay.load_signals(str(d / "run-1.json"), "Design")
    assert len(sigs) == 2          # better to test against something than nothing


def test_scoring_returns_before_and_after_for_each_signal(tmp_path):
    d = _debug(tmp_path, "run-1.json", SIGNALS)
    client = FakeClient(json.dumps({"scored": [
        {"i": 0, "score": 90, "title": "One", "reason": "r"},
        {"i": 1, "score": 30},
    ]}))
    out = replay.score_with(str(d / "run-1.json"), "AI", "MY PROMPT", client,
                            threshold=70)
    assert out["tested"] == 2
    assert out["passed"] == 1 and out["before_passed"] == 1
    rows = {r["title"]: r for r in out["rows"]}
    assert rows["a/one"]["before"] == 45 and rows["a/one"]["after"] == 90
    assert rows["@lab"]["before"] == 80 and rows["@lab"]["after"] == 30
    # the candidate prompt is what was actually sent
    assert client.calls[0][0]["content"] == "MY PROMPT"


def test_rows_are_sorted_by_the_new_score(tmp_path):
    d = _debug(tmp_path, "run-1.json", SIGNALS)
    client = FakeClient(json.dumps({"scored": [{"i": 0, "score": 10},
                                               {"i": 1, "score": 95}]}))
    out = replay.score_with(str(d / "run-1.json"), "AI", "P", client, threshold=70)
    assert [r["after"] for r in out["rows"]] == [95, 10]


def test_the_sample_is_capped_so_a_test_stays_cheap(tmp_path):
    many = [dict(SIGNALS[0], title=f"a/{i}") for i in range(500)]
    d = _debug(tmp_path, "run-1.json", many)
    client = FakeClient('{"scored":[]}')
    out = replay.score_with(str(d / "run-1.json"), "AI", "P", client,
                            threshold=70, limit=120)
    assert out["tested"] == 120
    assert out["total_available"] == 500


def test_a_signal_the_model_skips_is_reported_not_invented(tmp_path):
    d = _debug(tmp_path, "run-1.json", SIGNALS)
    client = FakeClient(json.dumps({"scored": [{"i": 0, "score": 90}]}))
    out = replay.score_with(str(d / "run-1.json"), "AI", "P", client, threshold=70)
    skipped = [r for r in out["rows"] if r["after"] is None]
    assert len(skipped) == 1 and skipped[0]["title"] == "@lab"


def test_a_broken_reply_leaves_a_usable_result(tmp_path):
    d = _debug(tmp_path, "run-1.json", SIGNALS)
    out = replay.score_with(str(d / "run-1.json"), "AI", "P",
                            FakeClient("not json"), threshold=70)
    assert out["tested"] == 2 and out["passed"] == 0
    assert all(r["after"] is None for r in out["rows"])
