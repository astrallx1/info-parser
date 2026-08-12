import json

import pytest
import yaml

from topicparser import prompts_loader as pl
from topicparser.api import Api

BASE = {"profiles": {"AI": {"github": {"topics": ["mcp"]},
                            "x": {"accounts": [], "lists": [], "searches": []}}}}
SIGNALS = [{"source": "github", "title": "a/one", "url": "https://github.com/a/one",
            "text": "A tool.", "score": 45}]


class FakeClient:
    def __init__(self, reply='{"scored":[{"i":0,"score":90,"title":"T","reason":"r"}]}'):
        self.reply, self.calls = reply, []

    def make(self, messages):
        self.calls.append(messages)
        return self.reply


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(pl.paths, "app_dir", lambda: str(tmp_path))
    path = tmp_path / "profiles.yaml"
    path.write_text(yaml.safe_dump(BASE, allow_unicode=True), encoding="utf-8")
    client = FakeClient()
    a = Api(profiles=yaml.safe_load(path.read_text(encoding="utf-8")),
            build_collectors=lambda: [], build_client=lambda: client,
            threshold=70, x_days=3, gh_days=60, profiles_path=str(path),
            debug_dir=str(tmp_path / "debug"))
    a._client = client
    return a


def _debug(api, tmp_path):
    d = tmp_path / "debug"
    d.mkdir(exist_ok=True)
    (d / "run-20260807-000000.json").write_text(json.dumps({
        "profiles": {"AI": {"scored": SIGNALS}}}), encoding="utf-8")


def test_the_candidate_prompt_is_sent_assembled_with_the_shared_rules(api, tmp_path):
    _debug(api, tmp_path)
    api.test_prompt("AI", "MY GATE RULES")
    system = api._client.calls[0][0]["content"]
    assert "MY GATE RULES" in system
    # without the shared machinery the model has no output contract and the test
    # would measure something the real run never does
    assert '{"scored":[{"i":<index>' in system
    assert "CALIBRATION" in system


def test_the_result_reports_before_and_after(api, tmp_path):
    _debug(api, tmp_path)
    out = api.test_prompt("AI", "RULES")
    assert out["ok"] and out["tested"] == 1
    assert out["rows"][0]["before"] == 45 and out["rows"][0]["after"] == 90
    assert out["passed"] == 1 and out["before_passed"] == 0


def test_with_no_run_of_your_own_the_shipped_sample_is_used(api):
    out = api.test_prompt("AI", "RULES")
    assert out["ok"] and out["tested"] > 0
    assert out["is_sample"] is True


def test_your_own_run_wins_over_the_sample(api, tmp_path):
    _debug(api, tmp_path)
    assert api.test_prompt("AI", "RULES")["is_sample"] is False


def test_an_empty_prompt_is_refused_before_any_call(api, tmp_path):
    _debug(api, tmp_path)
    assert "errors" in api.test_prompt("AI", "   ")
    assert api._client.calls == []


def test_a_shared_prompt_cannot_be_tested_as_a_profile(api, tmp_path):
    _debug(api, tmp_path)
    assert "errors" in api.test_prompt("_base", "RULES")


def test_testing_does_not_save_the_prompt(api, tmp_path):
    _debug(api, tmp_path)
    api.test_prompt("AI", "SOMETHING ELSE")
    assert not (tmp_path / "prompts" / "AI.txt").exists()


def test_the_threshold_is_the_saved_one_not_the_one_api_started_with(api, tmp_path,
                                                                     monkeypatch):
    """`run_parser` resolves the knobs at RUN time so a value saved in Settings reaches
    the next run without a restart. The prompt tester read the threshold the `Api` was
    CONSTRUCTED with, so it counted `passed` and `before_passed` against the old bar
    until the app restarted — the same resolve-at-construction trap already fixed in
    `run_parser` and the `.md` export."""
    monkeypatch.setattr("topicparser.paths.app_dir", lambda: str(tmp_path))
    _debug(api, tmp_path)
    api.save_tuning({"SCORE_THRESHOLD": "85"})

    out = api.test_prompt("AI", "RULES")

    assert out["threshold"] == 85
    assert out["passed"] == 1                 # the fake client scores it 90
    assert out["before_passed"] == 0          # the debug row scored 45


def test_no_knob_is_read_from_the_constructor_outside_the_defaults():
    """The resolve-at-construction trap, closed as a class rather than one caller at a
    time. It has been fixed four times now — `run_parser`, the `.md` export, the run
    itself, and the prompt tester — each time by routing one more reader through
    `_tuning()`. Every knob the `Api` is built with may be read in exactly two places:
    where it is stored, and where it becomes the fallback under `.env`.

    `_batch_size` is not here on purpose: it is deliberately off the Settings screen,
    so there is no saved value it could be shadowing."""
    import os
    import re

    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "topicparser", "api.py"), encoding="utf-8").read()
    defaults = src[src.index("def _tuning_defaults"):]
    defaults = defaults[:defaults.index("\n    def ", 1)]

    knobs = r"self\._(threshold|x_days|gh_days|feed_days|stagnant_days|min_velocity|off_interest)\b"
    stored = re.compile(knobs + r"\s*=\s*[a-z_]+( or set\(\))?$")
    for line in src.splitlines():
        if not re.search(knobs, line):
            continue
        if stored.match(line.strip()):
            continue                          # where __init__ stores it
        assert line in defaults, f"knob read outside _tuning_defaults: {line.strip()}"
