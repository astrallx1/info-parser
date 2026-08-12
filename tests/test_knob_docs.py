"""Every place a knob's default is written down, against the one place it is declared.

`X_MAX_TWEETS` stayed at 75 in the README's table after the default doubled to 150, so
the one document a new user reads understated the cost of a run by half. There are
three copies of those nine numbers and only one declaration, `tuning.KNOBS`.

`.env.example` is the copy that SHIPS, so it is checked without a skip; the README is
backed up in `docs/public/`, which never ships, so that half skips there instead — and
a knob is only documented if it appears in both, at the right value, with the prose
count above the table agreeing.
"""
import os
import re

import pytest

from topicparser import settings, tuning

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(ROOT, "docs", "public", "README.md")
ENV_EXAMPLE = os.path.join(ROOT, ".env.example")

# the prose above the table counts them in words: "Nine knobs, all editable in the app"
NUMBER_WORDS = ("zero one two three four five six seven eight nine ten eleven twelve "
                "thirteen fourteen fifteen").split()


def _shown(default) -> str:
    return "empty" if default == "" else str(int(default))


def _readme_table() -> dict:
    with open(README, encoding="utf-8") as f:
        return dict(re.findall(r"^\|\s*`([A-Z_]+)`\s*\|\s*([^|]+?)\s*\|", f.read(), re.M))


def test_env_example_carries_every_knob_at_its_real_default():
    """The copy that ships. `read_env` is the app's own parser, so a line this test
    accepts is a line the app reads the same way."""
    documented = settings.read_env(ENV_EXAMPLE)
    for knob in tuning.KNOBS:
        assert knob.name in documented, f"{knob.name} is missing from .env.example"
        expected = "" if knob.default == "" else str(int(knob.default))
        assert documented[knob.name] == expected, (
            f"{knob.name}: .env.example says {documented[knob.name]!r}, "
            f"the default is {expected!r}")


@pytest.mark.skipif(not os.path.exists(README), reason="docs/ does not ship")
def test_readme_documents_every_knob_at_its_real_default():
    documented = _readme_table()
    for knob in tuning.KNOBS:
        assert knob.name in documented, f"{knob.name} is missing from the README"
        assert documented[knob.name] == _shown(knob.default), (
            f"{knob.name}: README says {documented[knob.name]}, "
            f"the default is {_shown(knob.default)}")


@pytest.mark.skipif(not os.path.exists(README), reason="docs/ does not ship")
def test_the_readme_table_documents_nothing_that_is_no_longer_a_knob():
    """The other direction: a knob deleted from the declaration leaves its row behind,
    and a one-way check stays green while the README describes a setting that is gone."""
    assert set(_readme_table()) == {k.name for k in tuning.KNOBS}


@pytest.mark.skipif(not os.path.exists(README), reason="docs/ does not ship")
def test_the_readme_counts_the_knobs_it_lists():
    """The sentence above the table carries the count in words. A tenth knob would add
    a row, pass every check above, and leave 'Nine knobs' lying underneath it."""
    with open(README, encoding="utf-8") as f:
        text = f.read()
    assert f"{NUMBER_WORDS[len(tuning.KNOBS)].capitalize()} knobs" in text


# --- the knobs that are NOT on the Settings screen ---------------------------------
#
# Five knobs are deliberately hand-edited only (getting the X pacing wrong gets the
# account limited), so they never went through `tuning.KNOBS` — and each is declared in
# two or three places: `.env.example` documents it, `main.py` repeats it as the
# `env_num` fallback, and `XCollector.__init__` repeats it again as a parameter
# default. Nothing tied the copies together, and they drifted: `X_MAX_SCROLLS` was
# raised to 80 on 2026-08-21 while both fallbacks
# stayed at 40 and 5, so a fresh install with no `.env` got exactly the behaviour the
# measurements argue against.
#
# These read the LIVE sources, never a number copied into the test, which is the only
# form of this check that cannot itself go stale.

import inspect
import re

from topicparser.collectors.x import XCollector

# `.env` name -> the XCollector parameter mirroring it (None = not a collector arg)
HAND_KNOBS = {"X_MIN_DELAY": "min_delay", "X_MAX_DELAY": "max_delay",
              "X_MAX_SCROLLS": "max_scrolls",
              "LLM_BATCH_SIZE": None}


def _main_fallbacks() -> dict:
    """The literal each `env_num` falls back to, read out of `main.py`."""
    with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
        return dict(re.findall(r'config\.env_num\("([A-Z_]+)",\s*([0-9.]+)', f.read()))


def _collector_default(param):
    return inspect.signature(XCollector.__init__).parameters[param].default


@pytest.mark.parametrize("name", sorted(HAND_KNOBS))
def test_the_main_fallback_matches_what_env_example_documents(name):
    documented = settings.read_env(ENV_EXAMPLE)
    fallbacks = _main_fallbacks()
    assert name in fallbacks, f"{name} has no env_num fallback in main.py"
    assert float(fallbacks[name]) == float(documented[name]), (
        f"{name}: main.py falls back to {fallbacks[name]}, "
        f".env.example documents {documented[name]}")


@pytest.mark.parametrize("name", sorted(k for k, v in HAND_KNOBS.items() if v))
def test_the_collector_default_matches_what_env_example_documents(name):
    documented = settings.read_env(ENV_EXAMPLE)
    assert float(_collector_default(HAND_KNOBS[name])) == float(documented[name]), (
        f"{name}: XCollector defaults to {_collector_default(HAND_KNOBS[name])}, "
        f".env.example documents {documented[name]}")


def test_the_collectors_tweet_limit_matches_the_declared_knob():
    """`X_MAX_TWEETS` lives in `tuning.KNOBS`, so `main` passes it through `knobs[]` and
    never falls back — but the collector signature is a third copy of that number all
    the same."""
    assert _collector_default("limit") == tuning.BY_NAME["X_MAX_TWEETS"].default
