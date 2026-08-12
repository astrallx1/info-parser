"""`main.py` reads the tuning knobs, and a bad `.env` value must not stop the app.

The knobs on the Settings screen already fall back through `tuning.read`; these pin
the same promise onto the ones main.py casts itself, and onto the GitHub search
window, which was hardcoded and reachable from no knob at all."""
import main
from topicparser import config


def test_build_collectors_survives_a_broken_env(monkeypatch):
    monkeypatch.setenv("X_MIN_DELAY", "abc")
    monkeypatch.setenv("X_MAX_DELAY", "")
    monkeypatch.setenv("X_MAX_SCROLLS", "many")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    cols = main.build_collectors()
    assert [c.source for c in cols] == ["github", "feed", "x"]


def test_the_app_knobs_survive_a_broken_env(monkeypatch):
    monkeypatch.setenv("SCORE_THRESHOLD", "abc")
    monkeypatch.setenv("LLM_BATCH_SIZE", "lots")
    knobs = main.app_knobs()
    assert knobs["threshold"] == 70
    assert knobs["batch_size"] == 120


# --- the GitHub search window was reachable from no knob at all -------------------
# `created_within_days` defaulted to 90 and main.py never passed it, so raising
# GH_FRESH_DAYS to a year still found nothing created more than 90 days ago. It is
# a CEILING, not the freshness filter: the knob may lift it, never lower it, because
# a repo created 80 days ago and pushed yesterday is exactly what the 90 is there to
# catch and what a naive wiring to GH_FRESH_DAYS=60 would quietly lose.

def test_a_larger_gh_window_widens_the_github_search(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GH_FRESH_DAYS", "365")
    gh = main.build_collectors()[0]
    assert gh.created_within_days == 365


def test_the_default_gh_window_does_not_narrow_the_search(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GH_FRESH_DAYS", "60")
    gh = main.build_collectors()[0]
    assert gh.created_within_days == 90
