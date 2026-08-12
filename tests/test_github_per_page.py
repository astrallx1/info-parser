"""How wide the GitHub net is cast.

The collector asked for 30 repos per topic, which is a tiny slice: `topic:mcp`
created in the last 90 days matches ~24 500 repos. Widening the net does not touch
any scoring rule — the same gates simply see more candidates.
"""
import pytest
import responses

from topicparser.collectors.github import GitHubCollector

SEARCH = "https://api.github.com/search/repositories"


def _empty():
    responses.add(responses.GET, SEARCH, json={"items": []}, status=200)


@responses.activate
def test_default_asks_for_a_hundred_repos_per_topic():
    _empty()
    GitHubCollector(token="t").collect("AI", {"github": {"topics": ["mcp"]}})
    assert responses.calls[0].request.params["per_page"] == "100"


@responses.activate
def test_per_page_is_configurable():
    _empty()
    GitHubCollector(token="t", per_page=25).collect(
        "AI", {"github": {"topics": ["mcp"]}})
    assert responses.calls[0].request.params["per_page"] == "25"


@responses.activate
@pytest.mark.parametrize("asked,sent", [(500, "100"), (0, "1"), (-3, "1")])
def test_out_of_range_values_are_clamped(asked, sent):
    """GitHub rejects per_page above 100 with a 422 — a typo in `.env` must not
    take every GitHub topic down."""
    _empty()
    GitHubCollector(token="t", per_page=asked).collect(
        "AI", {"github": {"topics": ["mcp"]}})
    assert responses.calls[0].request.params["per_page"] == sent
