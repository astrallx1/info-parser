import responses
from topicparser.collectors.github import GitHubCollector

@responses.activate
def test_search_repos_maps_to_signals():
    responses.add(
        responses.GET, "https://api.github.com/search/repositories",
        json={"items": [{
            "full_name": "foo/bar", "description": "d" * 900,
            "html_url": "https://github.com/foo/bar",
            "stargazers_count": 1200, "pushed_at": "2026-07-07T00:00:00Z",
            "archived": False, "fork": False}]},
        status=200)
    c = GitHubCollector(token="t")
    sigs = c.collect("AI", {"github": {"topics": ["mcp"], "keywords": []}})
    assert len(sigs) == 1
    s = sigs[0]
    assert s.source == "github" and s.title == "foo/bar"
    assert s.stars == 1200 and len(s.description) == 500
    assert s.date == "2026-07-07T00:00:00Z"          # pushed_at = last modified


@responses.activate
def test_search_captures_created_date():
    # feed cards show the repo's creation date; the collector must capture created_at
    responses.add(
        responses.GET, "https://api.github.com/search/repositories",
        json={"items": [{
            "full_name": "foo/bar", "description": "d",
            "html_url": "https://github.com/foo/bar", "stargazers_count": 5,
            "created_at": "2026-05-01T00:00:00Z", "pushed_at": "2026-07-07T00:00:00Z",
            "archived": False, "fork": False}]},
        status=200)
    sigs = GitHubCollector(token="t").collect("AI", {"github": {"topics": ["mcp"]}})
    assert sigs[0].created == "2026-05-01T00:00:00Z"

@responses.activate
def test_dedupes_same_repo_across_topics():
    # a repo tagged with several of the profile's topics returns from each search;
    # it must be collected ONCE, not once per topic (was flooding the LLM payload).
    responses.add(responses.GET, "https://api.github.com/search/repositories",
        json={"items": [{
            "full_name": "dup/repo", "description": "d",
            "html_url": "https://github.com/dup/repo", "stargazers_count": 50,
            "pushed_at": "2026-07-07T00:00:00Z", "archived": False, "fork": False}]},
        status=200)
    c = GitHubCollector(token="t")
    sigs = c.collect("AI", {"github": {"topics": ["mcp", "llm", "ai-agents"]}})
    assert len(sigs) == 1


@responses.activate
def test_skips_archived_and_forks():
    responses.add(responses.GET, "https://api.github.com/search/repositories",
        json={"items": [
            {"full_name": "a/x", "html_url": "u1", "stargazers_count": 5,
             "pushed_at": "2026-07-07T00:00:00Z", "archived": True, "fork": False},
            {"full_name": "a/y", "html_url": "u2", "stargazers_count": 5,
             "pushed_at": "2026-07-07T00:00:00Z", "archived": False, "fork": True}]},
        status=200)
    c = GitHubCollector(token="t")
    assert c.collect("AI", {"github": {"topics": ["mcp"], "keywords": []}}) == []
