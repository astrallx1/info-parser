import responses, topicparser.store as store
from topicparser.collectors.github import GitHubCollector

@responses.activate
def test_measure_tracked_records_stars(tmp_path):
    store.DB_PATH = str(tmp_path/"t.db"); store.init_db()
    store.add_tracked_repo("foo/bar")
    responses.add(responses.GET, "https://api.github.com/repos/foo/bar",
                  json={"stargazers_count": 1200}, status=200)
    GitHubCollector(token="t").measure_tracked()
    assert store.velocity("foo/bar") is None   # only one measure so far, but row exists
    from topicparser.store import _session, StarHistory
    with _session() as s:
        assert s.query(StarHistory).count() == 1
