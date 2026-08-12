"""Settings can change how the tool judges, and the change reaches the NEXT run.

`Api` used to freeze every knob at construction, so even editing `.env` by hand needed
a restart. The screen would have been worse than useless: it would have said 85 while
the run still used 70.
"""
import dataclasses

import pytest

from topicparser import settings, tuning
from topicparser.api import Api


def make(tmp_path, monkeypatch, **kw):
    env = tmp_path / ".env"
    env.write_text("# keep me\nGITHUB_TOKEN=t\nSCORE_THRESHOLD=70\n", encoding="utf-8")
    monkeypatch.setattr("topicparser.paths.app_dir", lambda: str(tmp_path))
    for k in tuning.KNOBS:
        monkeypatch.delenv(k.name, raising=False)
    api = Api(profiles={"profiles": {}}, build_collectors=lambda: [],
              build_client=lambda: None, threshold=80, x_days=3, gh_days=21, **kw)
    return api, env


def test_get_tuning_returns_the_current_values_and_the_knob_shapes(tmp_path, monkeypatch):
    api, _ = make(tmp_path, monkeypatch)
    out = api.get_tuning()
    names = [k["name"] for k in out["knobs"]]
    assert "SCORE_THRESHOLD" in names and "OFF_INTEREST" in names
    assert out["values"]["SCORE_THRESHOLD"] == 80        # what the Api was built with
    assert out["values"]["GH_PER_PAGE"] == 100           # the declared default
    shape = next(k for k in out["knobs"] if k["name"] == "GH_PER_PAGE")
    assert shape["min"] == 1 and shape["max"] == 100 and shape["kind"] == "int"


def test_saving_writes_the_env_and_keeps_the_rest_of_the_file(tmp_path, monkeypatch):
    api, env = make(tmp_path, monkeypatch)
    assert api.save_tuning({"SCORE_THRESHOLD": "85", "GH_PER_PAGE": "40"}) == {"ok": True}
    text = env.read_text(encoding="utf-8")
    assert "SCORE_THRESHOLD=85" in text
    assert "GH_PER_PAGE=40" in text
    assert "# keep me" in text and "GITHUB_TOKEN=t" in text


def test_a_saved_value_reaches_the_next_run_without_a_restart(tmp_path, monkeypatch):
    api, _ = make(tmp_path, monkeypatch)
    seen = {}

    def fake_run(**kw):
        seen.update(kw)
        return {"topics": [], "alerts": [], "warnings": []}

    monkeypatch.setattr("topicparser.api.run", fake_run)
    api._profiles = {"profiles": {"AI": {}}}
    selection = {"AI": {"github": {"topics": ["mcp"]}, "x": {}}}

    api.run_parser(selection)
    assert seen["threshold"] == 80          # the constructor value, nothing saved yet

    api.save_tuning({"SCORE_THRESHOLD": "55", "X_FRESH_DAYS": "7"})
    api.run_parser(selection)
    assert seen["threshold"] == 55
    assert seen["x_days"] == 7


def test_off_interest_reaches_the_run_as_a_set(tmp_path, monkeypatch):
    api, _ = make(tmp_path, monkeypatch)
    seen = {}
    monkeypatch.setattr("topicparser.api.run",
                        lambda **kw: seen.update(kw) or {"topics": [], "alerts": [],
                                                         "warnings": []})
    api.save_tuning({"OFF_INTEREST": "Novabyte, Polaris"})
    api.run_parser({"AI": {"github": {"topics": ["mcp"]}, "x": {}}})
    assert seen["off_interest"] == {"novabyte", "polaris"}


def test_clearing_off_interest_is_honoured(tmp_path, monkeypatch):
    """An empty text knob is a CHOICE. `save_settings` treats a blank field as
    "leave it alone" because its inputs are masked keys; this one must not."""
    api, env = make(tmp_path, monkeypatch)
    api.save_tuning({"OFF_INTEREST": "novabyte"})
    api.save_tuning({"OFF_INTEREST": ""})
    assert 'OFF_INTEREST=""' in env.read_text(encoding="utf-8") or \
           "OFF_INTEREST=\n" in env.read_text(encoding="utf-8")
    assert api.get_tuning()["values"]["OFF_INTEREST"] == ""


@pytest.mark.parametrize("bad", [{"GH_PER_PAGE": "1000"}, {"SCORE_THRESHOLD": "900"},
                                 {"OPENAI_API_KEY": "sk-x"}])
def test_a_bad_value_is_refused_and_nothing_is_written(tmp_path, monkeypatch, bad):
    api, env = make(tmp_path, monkeypatch)
    before = env.read_text(encoding="utf-8")
    res = api.save_tuning(bad)
    assert res.get("errors")
    assert env.read_text(encoding="utf-8") == before


def test_tuning_cannot_be_changed_mid_run(tmp_path, monkeypatch):
    """Half a run would use the old numbers and half the new ones, and the debug log
    would record neither."""
    api, _ = make(tmp_path, monkeypatch)
    api._running = True
    assert api.save_tuning({"SCORE_THRESHOLD": "55"}).get("errors")


def test_an_unset_constructor_value_does_not_beat_the_declared_default(tmp_path, monkeypatch):
    """`off_interest` is an empty set when nobody supplies one. Passing that down as a
    "default" outranked the declaration and quietly turned the whole filter off — measured
    against the real app, where `get_tuning` came back with an empty Off-interest field.

    `OFF_INTEREST` ships empty today, so this declares its own non-empty default: the
    rule is about the resolution order and must hold whatever the shipped value is."""
    declared = [dataclasses.replace(k, default="polaris") if k.name == "OFF_INTEREST" else k
                for k in tuning.KNOBS]
    monkeypatch.setattr(tuning, "KNOBS", declared)
    api, _ = make(tmp_path, monkeypatch)          # no off_interest= given
    assert api.get_tuning()["values"]["OFF_INTEREST"] == "polaris"


def test_a_deliberately_cleared_value_still_wins(tmp_path, monkeypatch):
    """Clearing the field is a choice and must survive the rule above."""
    api, _ = make(tmp_path, monkeypatch)
    api.save_tuning({"OFF_INTEREST": ""})
    assert api.get_tuning()["values"]["OFF_INTEREST"] == ""
