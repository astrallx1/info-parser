import topicparser.store as store
from topicparser.models import Signal
from topicparser.pipeline import run

from datetime import datetime, timedelta, timezone

# Freshness is measured against NOW, so a hardcoded date silently ages out of the
# window and switches these tests off (it did, on 2026-07-29). Always relative.
FRESH = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ')


class Col:
    source = "github"
    def collect(self, n, c):
        return [Signal.make(source="github", title="foo/bar", description="d",
                url="u1", date=FRESH, profile=n, stars=5)]
    def measure_tracked(self): pass
    def attach_velocity(self, sigs): return sigs

class Client:
    def make(self, m):
        return ('{"scored":[{"i":0,"score":95,"reason":"r","title":"Great topic"}],'
                '"groups":[]}')

def test_full_run(tmp_path):
    store.DB_PATH = str(tmp_path/"t.db"); store.init_db()
    out = run(selected=["AI"], profiles={"AI": {"github": {"topics": ["mcp"]}}},
              collectors=[Col()], client=Client(), threshold=80, x_days=3, gh_days=21)["topics"]
    assert out[0]["title"] == "Great topic"
    assert store.get_recent_topics(days=1)[0]["score"] == 95
