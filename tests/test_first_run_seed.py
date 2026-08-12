"""A fresh download gets one profile, not an empty app.

An example yaml shipped in the repo but nothing ever copied it, so a new user
landed on "no profiles, add one in the Profiles tab" with nothing to run and no example
of what a source even looks like. The seed is deliberately small: one profile, two
accounts, no rules — enough to see the shape, not enough to pretend it is tuned.
"""
import os

import pytest
import yaml

from topicparser import config
from topicparser import prompts_loader as pl


@pytest.fixture(autouse=True)
def _isolate_app_dir(tmp_path, monkeypatch):
    """Seeding writes a prompt BESIDE THE APP, so an unpatched test writes into the
    real repo and shadows the author's own tuned rules. It did exactly that once."""
    monkeypatch.setattr(pl.paths, "app_dir", lambda: str(tmp_path))


def test_a_missing_profiles_file_is_seeded(tmp_path):
    path = str(tmp_path / "profiles.yaml")

    data = config.load_profiles(path)

    assert list(data["profiles"]) == ["AI"]
    assert os.path.exists(path), "the seed is written, so the next launch is unchanged"


def test_the_seeded_profile_holds_the_two_accounts_and_nothing_else(tmp_path):
    path = str(tmp_path / "profiles.yaml")

    ai = config.load_profiles(path)["profiles"]["AI"]

    assert ai["x"]["accounts"] == ["OpenAI", "AnthropicAI"]
    assert ai["x"]["lists"] == [] and ai["x"]["searches"] == []
    assert ai["github"]["topics"] == ["llm", "ai-agents", "mcp"]


def test_the_seed_survives_a_round_trip_through_validation(tmp_path):
    """It is written to disk, so it must pass the same checks a hand-edited file does."""
    path = str(tmp_path / "profiles.yaml")

    assert config.validate_profiles(config.load_profiles(path)) == []


def test_an_existing_file_is_never_overwritten(tmp_path):
    path = tmp_path / "profiles.yaml"
    path.write_text(yaml.safe_dump({"profiles": {"Mine": {"github": {"topics": ["mcp"]}}}}),
                    encoding="utf-8")

    data = config.load_profiles(str(path))

    assert list(data["profiles"]) == ["Mine"]


def test_a_file_the_user_emptied_is_left_alone(tmp_path):
    """Deleting every profile is a choice; re-seeding would fight the user."""
    path = tmp_path / "profiles.yaml"
    path.write_text(yaml.safe_dump({"profiles": {}}), encoding="utf-8")

    assert config.load_profiles(str(path))["profiles"] == {}


def test_seeding_survives_an_unwritable_folder(tmp_path):
    """Read-only install directory: still return the seed rather than crash."""
    path = str(tmp_path / "nope" / "profiles.yaml")

    data = config.load_profiles(path)

    assert list(data["profiles"]) == ["AI"]


def test_the_seeded_profile_does_not_inherit_the_authors_tuned_rules(tmp_path):
    """The repo ships AI.txt — 280 lines of the author's own taste. A fresh install
    must NOT start scoring by it: the seed writes the starter text beside the app,
    which wins over the packaged copy."""
    config.load_profiles(str(tmp_path / "profiles.yaml"))

    text = pl.read_prompt("AI")
    assert "Your rules go here" in text
    assert "PROFILE FOCUS" not in text


def test_seeding_never_overwrites_a_prompt_that_already_exists(tmp_path):
    pl.save_profile_prompt("AI", "MY OWN RULES")

    config.load_profiles(str(tmp_path / "profiles.yaml"))

    assert pl.read_prompt("AI") == "MY OWN RULES"


def test_the_seed_carries_official_sources_too(tmp_path):
    """The third source shipped with nothing to point at, so a fresh install ran on
    GitHub and X only and the «Першоджерела» block read as decoration. Three feeds:
    two lab blogs and Anthropic's YouTube channel, because Anthropic publishes no RSS
    at all."""
    ai = config.load_profiles(str(tmp_path / "profiles.yaml"))["profiles"]["AI"]

    urls = ai["feeds"]["urls"]
    assert urls, "a seeded profile with no feeds cannot show what the source is for"
    assert all(u.startswith("https://") for u in urls)
    assert any("openai.com" in u for u in urls)
    assert any("youtube.com/feeds/videos.xml?channel_id=" in u for u in urls)


def test_the_seed_carries_github_topics():
    """GitHub is the source with the lowest barrier — a token with no scopes, no
    cookies, no browser — and the guide tells the user they may skip the X step. With
    an empty `topics` the one source everybody has produced nothing on the documented
    happy path, while the README promises a quick GitHub-only pass.

    Pinned like the knob table: the next tidy-up must not quietly empty it again."""
    topics = config.SEED_PROFILES["profiles"]["AI"]["github"]["topics"]

    assert topics, "a seeded profile with no GitHub topics collects nothing from GitHub"
    for t in topics:
        assert config._GH_TOPIC.match(t), f"{t!r} would be refused by the source check"

