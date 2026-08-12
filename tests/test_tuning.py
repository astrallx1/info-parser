"""The tuning knobs, and the rule that they take effect on the NEXT run.

They lived in `.env` only, which sat oddly beside a Settings screen built so nobody has
to find a dotfile. Two things have to hold or the screen lies:

* a value saved from Settings must reach the run WITHOUT a restart — the pipeline used
  to read every knob once, at `Api` construction;
* a bad value must be REFUSED, not written. `GH_PER_PAGE=1000` makes GitHub answer 422
  for every topic, and a threshold of 900 makes every run come back empty.
"""
import pytest

from topicparser import tuning


def test_every_knob_has_a_default_and_a_range():
    for k in tuning.KNOBS:
        assert k.name and k.default is not None
        if k.kind in ("int", "float"):
            assert k.minimum is not None and k.maximum is not None
            assert k.minimum <= float(k.default) <= k.maximum


def test_read_falls_back_to_the_declared_defaults(monkeypatch):
    for k in tuning.KNOBS:
        monkeypatch.delenv(k.name, raising=False)
    values = tuning.read()
    assert values["SCORE_THRESHOLD"] == 70
    assert values["GH_PER_PAGE"] == 100
    # nothing is off-interest until the reader names a subject: a shipped default
    # would hand a stranger somebody else's taste
    assert values["OFF_INTEREST"] == ""


def test_the_environment_wins_over_the_defaults(monkeypatch):
    monkeypatch.setenv("SCORE_THRESHOLD", "85")
    assert tuning.read()["SCORE_THRESHOLD"] == 85


def test_caller_defaults_win_over_the_declared_ones_but_not_over_the_env(monkeypatch):
    """`Api` passes what it was constructed with, so a test that builds an Api with
    threshold=80 keeps it — while a real `.env` still overrides."""
    for k in tuning.KNOBS:
        monkeypatch.delenv(k.name, raising=False)
    assert tuning.read({"SCORE_THRESHOLD": 80})["SCORE_THRESHOLD"] == 80
    monkeypatch.setenv("SCORE_THRESHOLD", "55")
    assert tuning.read({"SCORE_THRESHOLD": 80})["SCORE_THRESHOLD"] == 55


def test_an_unreadable_value_falls_back_instead_of_killing_the_run(monkeypatch):
    monkeypatch.setenv("SCORE_THRESHOLD", "seventy")
    assert tuning.read()["SCORE_THRESHOLD"] == 70


@pytest.mark.parametrize("name,value", [
    ("SCORE_THRESHOLD", "900"),
    ("SCORE_THRESHOLD", "-1"),
    ("GH_PER_PAGE", "1000"),          # GitHub answers 422 above 100
    ("GH_PER_PAGE", "0"),
    ("X_MAX_TWEETS", "0"),
    ("X_FRESH_DAYS", "0"),
    ("TREND_MIN_VELOCITY", "-5"),
    ("SCORE_THRESHOLD", "abc"),
])
def test_a_value_outside_its_range_is_refused(name, value):
    from topicparser import i18n

    errs = tuning.validate({name: value})
    # the message names the FIELD LABEL, not the variable — it lands in a toast next
    # to the input the reader is looking at
    assert errs and i18n.t(f"tune.{name}") in errs[0]


def test_a_valid_set_passes_and_comes_back_as_strings_for_the_env():
    values = {"SCORE_THRESHOLD": "75", "GH_PER_PAGE": "50", "OFF_INTEREST": "novabyte, polaris"}
    assert tuning.validate(values) == []
    assert tuning.for_env(values) == {"SCORE_THRESHOLD": "75", "GH_PER_PAGE": "50",
                                      "OFF_INTEREST": "novabyte, polaris"}


def test_an_unknown_knob_is_refused():
    """This screen writes `.env`; it must not become a way to set any variable."""
    assert tuning.validate({"OPENAI_API_KEY": "sk-x"})


def test_off_interest_may_be_emptied():
    """Clearing it means "nothing is off-interest", which is a legitimate choice —
    an empty string must not read as "leave the old value alone"."""
    assert tuning.validate({"OFF_INTEREST": ""}) == []
    assert tuning.for_env({"OFF_INTEREST": ""}) == {"OFF_INTEREST": ""}


def test_off_interest_reaches_the_pipeline_as_a_lowercased_set(monkeypatch):
    monkeypatch.setenv("OFF_INTEREST", "Novabyte, Polaris ,, ")
    assert tuning.off_interest_terms(tuning.read()) == {"novabyte", "polaris"}


def test_a_value_carrying_both_quote_kinds_is_refused():
    """`.env` quotes a value that carries a space, and has no escape for a quote inside
    the quotes — so a value holding both kinds cannot be written at all. Refusing it is
    honest; writing something that reads back truncated is the bug this closes."""
    from topicparser import i18n

    errs = tuning.validate({"OFF_INTEREST": 'say "hi", what\'s new'})
    assert errs and i18n.t("tune.OFF_INTEREST") in errs[0]


@pytest.mark.parametrize("value", ['say "hi", crypto', "what's new, crypto"])
def test_one_kind_of_quote_is_fine(value):
    assert tuning.validate({"OFF_INTEREST": value}) == []
