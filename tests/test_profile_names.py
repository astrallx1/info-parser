"""A profile name becomes a FILENAME (`<name>.txt` in the prompts folder), so the
moment the UI can create profiles, an unvalidated name is a path-traversal hole.
Validation lives in one place and every write goes through it."""
import pytest

from topicparser import config


@pytest.mark.parametrize("name", [
    "AI", "Crypto", "Design Tools", "web3_news", "ai-agents", "Дизайн", "設計",
])
def test_ordinary_names_are_accepted(name):
    assert config.validate_profile_name(name) == []


@pytest.mark.parametrize("name", [
    "../evil", "..\\evil", "a/b", "a\\b", "..", ".", "a/../b",
])
def test_a_name_that_can_escape_the_folder_is_rejected(name):
    assert config.validate_profile_name(name)


@pytest.mark.parametrize("name", ["", "   ", "\t"])
def test_an_empty_name_is_rejected(name):
    assert config.validate_profile_name(name)


def test_an_absurdly_long_name_is_rejected():
    assert config.validate_profile_name("x" * 200)


@pytest.mark.parametrize("name", ["CON", "nul", "COM1", "LPT9", "aux"])
def test_windows_reserved_device_names_are_rejected(name):
    # the owner's other machine is Windows: `CON.txt` is not a file there
    assert config.validate_profile_name(name)


@pytest.mark.parametrize("name", ["a\x00b", "a\nb", "tab\there"])
def test_control_characters_are_rejected(name):
    assert config.validate_profile_name(name)


@pytest.mark.parametrize("name", ["_base", "_group", "_xgate", "_dedup", "_language.en"])
def test_a_name_colliding_with_a_shared_prompt_is_rejected(name):
    # `_base.txt` is machinery; a profile called `_base` would overwrite it
    assert config.validate_profile_name(name)


def test_a_trailing_dot_or_space_is_rejected():
    # Windows silently strips them, so "AI " and "AI" would fight over one file
    assert config.validate_profile_name("AI ")
    assert config.validate_profile_name("AI.")
