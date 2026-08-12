"""Sources have a SHAPE, and the app used to accept anything.

A Cyrillic X handle was accepted, saved, listed in the picker and then RUN — the
scrape spent minutes on a URL that cannot exist. Handles, list ids and GitHub topics
are all ASCII with narrow rules, so they are checked before they can be saved.
Searches are free text and deliberately stay unchecked.
"""
from topicparser import config


def _p(**sources):
    return {"profiles": {"AI": sources}}


def test_a_cyrillic_handle_is_refused():
    errs = config.validate_profiles(_p(x={"accounts": ["фівфіві"]}))

    assert errs and "фівфіві" in errs[0]


def test_ordinary_handles_pass():
    assert config.validate_profiles(
        _p(x={"accounts": ["OpenAI", "aiedge_", "sama", "a1_B2"]})) == []


def test_a_handle_over_fifteen_characters_is_refused():
    assert config.validate_profiles(_p(x={"accounts": ["a" * 16]}))


def test_a_handle_with_punctuation_is_refused():
    assert config.validate_profiles(_p(x={"accounts": ["open ai"]}))
    assert config.validate_profiles(_p(x={"accounts": ["open.ai"]}))
    assert config.validate_profiles(_p(x={"accounts": ["@openai"]}))


def test_a_list_id_must_be_digits():
    assert config.validate_profiles(_p(x={"lists": [{"id": "abc", "name": "x"}]}))
    assert config.validate_profiles(_p(x={"lists": [{"id": "1234567890123456789", "name": "x"}]})) == []


def test_a_github_topic_must_be_lowercase_ascii():
    assert config.validate_profiles(_p(github={"topics": ["Штучний"]}))
    assert config.validate_profiles(_p(github={"topics": ["AI Agents"]}))
    assert config.validate_profiles(_p(github={"topics": ["ai-agents", "mcp", "llm"]})) == []


def test_searches_are_free_text():
    """A search is a query, not an identifier — quotes, colons and Cyrillic are all
    legitimate there."""
    assert config.validate_profiles(
        _p(x={"searches": ['"claude code" min_faves:50', "штучний інтелект"]})) == []


def test_an_empty_search_is_still_refused():
    assert config.validate_profiles(_p(x={"searches": ["   "]}))


def test_the_error_names_the_profile_and_the_value():
    errs = config.validate_profiles(_p(x={"accounts": ["фівфіві"]}))

    assert "AI" in errs[0]
