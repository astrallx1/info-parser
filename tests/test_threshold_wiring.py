"""`SCORE_THRESHOLD` used to work in one direction only. `pipeline` never passed
`keep=` to `ranker.rank`, so the ranker cut at its own default 70 and the pipeline
filtered a second time afterwards: anything below 70 had already been thrown away
before the knob was consulted. The Settings screen offers 0-100, so the low half of
that range was a knob wired to nothing."""
from datetime import datetime, timedelta, timezone

import topicparser.pipeline as pipeline
import topicparser.store as store
from topicparser.models import Signal

FRESH = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeCollector:
    source = "github"

    def collect(self, name, cfg):
        return [Signal.make(source="github", title="foo/bar", description="d",
                            url="u1", date=FRESH, profile=name, stars=9)]


class FakeClient:
    def make(self, messages):
        return ('{"scored":[{"i":0,"score":55,"reason":"r","title":"T"}],'
                '"groups":[]}')


def test_the_threshold_reaches_the_ranker(tmp_path, monkeypatch):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    seen = {}
    real = pipeline.ranker.rank

    def spy(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)

    monkeypatch.setattr(pipeline.ranker, "rank", spy)
    pipeline.run(selected=["AI"], profiles={"AI": {"github": {"topics": ["mcp"]}}},
                 collectors=[FakeCollector()], client=FakeClient(), threshold=50,
                 x_days=3, gh_days=21)
    assert seen.get("keep") == 50


def test_a_threshold_below_70_actually_lets_a_signal_through(tmp_path):
    # the whole point of the knob: a 55 must reach the feed when the bar is 50
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    topics = pipeline.run(selected=["AI"],
                          profiles={"AI": {"github": {"topics": ["mcp"]}}},
                          collectors=[FakeCollector()], client=FakeClient(),
                          threshold=50, x_days=3, gh_days=21)["topics"]
    assert [t["title"] for t in topics] == ["T"]
    assert topics[0]["score"] == 55


def test_a_higher_threshold_still_cuts(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    topics = pipeline.run(selected=["AI"],
                          profiles={"AI": {"github": {"topics": ["mcp"]}}},
                          collectors=[FakeCollector()], client=FakeClient(),
                          threshold=80, x_days=3, gh_days=21)["topics"]
    assert topics == []
