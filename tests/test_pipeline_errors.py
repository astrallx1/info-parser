import topicparser.store as store
from topicparser.pipeline import run

class BoomCollector:
    source = "github"
    def collect(self, name, cfg): raise RuntimeError("api down")

class FakeClient:
    # scores whatever it is given: a client that answers and scores NOTHING is its own
    # failure now (see test_score_failure_visible) and would warn here
    def make(self, m):
        return '{"scored":[{"i":0,"score":90,"reason":"r","title":"T"}]}'

def test_run_survives_collector_error(tmp_path):
    store.DB_PATH = str(tmp_path/"t.db"); store.init_db()
    out = run(selected=["AI"], profiles={"AI": {"github": {"topics": ["x"]}}},
              collectors=[BoomCollector()], client=FakeClient(),
              threshold=80, x_days=3, gh_days=21)
    assert out["topics"] == []                    # no crash, empty result
    assert any("could not collect" in w for w in out["warnings"])   # failure surfaced


class OneSignalCollector:
    source = "github"
    def collect(self, name, cfg):
        from datetime import datetime, timezone
        from topicparser.models import Signal
        return [Signal.make(source="github", title="a/b", description="d",
                            url="https://github.com/a/b",
                            date=datetime.now(timezone.utc).isoformat(), profile=name)]


def test_run_warns_when_the_scoring_prompt_is_missing(tmp_path):
    # An empty prompt means the ranker silently falls back to its 14-line
    # DEFAULT_SYSTEM and every tuned rule is gone — the exact failure a packaged
    # build hits when the prompt files did not ship. It must be visible, not silent.
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    out = run(selected=["AI"], profiles={"AI": {"github": {"topics": ["x"]}}},
              collectors=[OneSignalCollector()], client=FakeClient(),
              threshold=80, x_days=3, gh_days=21,
              prompt_loader=lambda name: "")
    assert any("scoring prompt" in w.lower() for w in out["warnings"])


def test_run_is_quiet_when_the_prompt_loads(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    out = run(selected=["AI"], profiles={"AI": {"github": {"topics": ["x"]}}},
              collectors=[OneSignalCollector()], client=FakeClient(),
              threshold=80, x_days=3, gh_days=21,
              prompt_loader=lambda name: "REAL RULES")
    assert out["warnings"] == []
