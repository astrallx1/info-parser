import responses
from topicparser.collectors.github import GitHubCollector
from topicparser import ranker
from topicparser.models import Signal


def _item(**over):
    it = {"full_name": "foo/bar", "description": "d",
          "html_url": "https://github.com/foo/bar", "stargazers_count": 5,
          "created_at": "2026-05-01T00:00:00Z", "pushed_at": "2026-07-07T00:00:00Z",
          "archived": False, "fork": False}
    it.update(over)
    return it


@responses.activate
def test_collector_captures_the_repo_topics():
    """GitHub already returns a repo's own tags in the same search response — free,
    no extra call. They were being thrown away, so the cards had nothing to show."""
    responses.add(responses.GET, "https://api.github.com/search/repositories",
                  json={"items": [_item(topics=["no-code", "python", "vibe-coding"])]},
                  status=200)
    sigs = GitHubCollector(token="t").collect("AI", {"github": {"topics": ["mcp"]}})
    assert sigs[0].topics == ["no-code", "python", "vibe-coding"]


@responses.activate
def test_a_repo_without_topics_gets_an_empty_list():
    responses.add(responses.GET, "https://api.github.com/search/repositories",
                  json={"items": [_item()]}, status=200)
    sigs = GitHubCollector(token="t").collect("AI", {"github": {"topics": ["mcp"]}})
    assert sigs[0].topics == []


@responses.activate
def test_the_profiles_own_topics_come_first():
    """A repo self-tags 10-20 tags and the card shows only the first few, so the ones
    the owner actually searches for must lead — otherwise the card shows `python`."""
    responses.add(responses.GET, "https://api.github.com/search/repositories",
                  json={"items": [_item(topics=["python", "rust", "mcp", "llm"])]},
                  status=200)
    sigs = GitHubCollector(token="t").collect(
        "AI", {"github": {"topics": ["mcp", "llm"]}})
    assert sigs[0].topics[:2] == ["mcp", "llm"]
    assert sorted(sigs[0].topics) == ["llm", "mcp", "python", "rust"]   # nothing lost


def test_repo_meta_carries_topics_onto_the_topic_card():
    sig = Signal.make(source="github", title="foo/bar", description="d",
                      url="https://github.com/foo/bar", date="2026-07-07T00:00:00Z",
                      profile="AI", stars=5, topics=["no-code", "beginners"])
    assert ranker._repo_meta(sig)["topics"] == ["no-code", "beginners"]


def test_repo_meta_gives_a_tweet_no_topics():
    sig = Signal.make(source="x", title="@who", description="t",
                      url="https://x.com/who/status/1", date="2026-07-07T00:00:00Z",
                      profile="AI")
    assert ranker._repo_meta(sig)["topics"] == []
