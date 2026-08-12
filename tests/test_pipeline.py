import threading
import pytest
import topicparser.store as store
from topicparser.models import Signal
from topicparser.pipeline import run, RunCancelled

from datetime import datetime, timedelta, timezone

# Freshness is measured against NOW, so a hardcoded date silently ages out of the
# window and switches these tests off (it did, on 2026-07-29). Always relative.
FRESH = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ')


class FakeCollector:
    source = "github"
    def collect(self, name, cfg):
        return [Signal.make(source="github", title="foo/bar", description="d",
                url="u1", date=FRESH, profile=name, stars=9)]

class FakeClient:
    # call 1 = scoring (reads "scored"), call 2 = grouping (reads "groups");
    # one blob serves both — the topic itself is assembled in code from the
    # scored entry (title "T", score 90, url u1).
    def make(self, messages):
        return ('{"scored":[{"i":0,"score":90,"reason":"r","title":"T"}],'
                '"groups":[]}')

def test_run_reports_coarse_progress_phases(tmp_path):
    # coarse phase labels only (no counts, no timer): "Collecting <source>", "Scoring"
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    seen = []
    run(selected=["AI"], profiles={"AI": {"github": {"topics": ["mcp"]}}},
        collectors=[FakeCollector()], client=FakeClient(), threshold=80,
        x_days=3, gh_days=21, progress=seen.append)
    assert any("Collecting" in p and "GitHub" in p for p in seen)
    assert any("Scoring" in p for p in seen)


def test_run_without_progress_is_unaffected(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    topics = run(selected=["AI"], profiles={"AI": {"github": {"topics": ["mcp"]}}},
                 collectors=[FakeCollector()], client=FakeClient(), threshold=80,
                 x_days=3, gh_days=21)["topics"]
    assert [t["title"] for t in topics] == ["T"]


def test_run_returns_only_above_threshold_and_stores(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    profiles = {"AI": {"github": {"topics": ["mcp"], "keywords": []}}}
    topics = run(selected=["AI"], profiles=profiles, collectors=[FakeCollector()],
                 client=FakeClient(), threshold=80, x_days=3, gh_days=21)["topics"]
    assert [t["title"] for t in topics] == ["T"]          # 50 dropped
    assert store.get_recent_topics(days=1)[0]["title"] == "T"

def test_run_drops_banned_repo(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    store.ban_repo("foo/bar")
    profiles = {"AI": {"github": {"topics": ["mcp"]}}}
    topics = run(selected=["AI"], profiles=profiles, collectors=[FakeCollector()],
                 client=FakeClient(), threshold=80, x_days=3, gh_days=21)["topics"]
    assert topics == []                                   # banned pre-LLM

def test_auto_track_stores_ukrainian_why_as_description(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    profiles = {"AI": {"github": {"topics": ["mcp"]}}}
    run(selected=["AI"], profiles=profiles, collectors=[FakeCollector()],
        client=FakeClient(), threshold=80, x_days=3, gh_days=21)
    detail = {d["repo"]: d for d in store.get_tracked_detail()}
    assert detail["foo/bar"]["description"] == "r"        # the topic's Ukrainian why, not English "d"

def test_run_dedups_by_seen_link(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    store.insert_topic(title="old", why="w", links=["u1"], signature="s",
                       score=90, profile="AI")
    profiles = {"AI": {"github": {"topics": ["mcp"], "keywords": []}}}
    topics = run(selected=["AI"], profiles=profiles, collectors=[FakeCollector()],
                 client=FakeClient(), threshold=80, x_days=3, gh_days=21)["topics"]
    assert topics == []                                   # u1 already seen -> dropped pre-LLM

class SpyClient:
    def __init__(self): self.systems = []
    def make(self, messages):
        self.systems.append(messages[0]["content"])
        return '{"topics":[{"title":"T","why":"W","score":90,"links":["u1"]}],"scored":[]}'

def test_run_uses_prompt_loader_per_profile(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    client = SpyClient()
    run(selected=["AI"], profiles={"AI": {"github": {"topics": ["mcp"]}}},
        collectors=[FakeCollector()], client=client, threshold=80,
        x_days=3, gh_days=21, prompt_loader=lambda name: f"RULES FOR {name}")
    assert any("RULES FOR AI" in s for s in client.systems)

def test_run_writes_debug_log(tmp_path):
    import json, glob
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    dbg = tmp_path / "debug"
    run(selected=["AI"], profiles={"AI": {"github": {"topics": ["mcp"]}}},
        collectors=[FakeCollector()], client=SpyClient(), threshold=80,
        x_days=3, gh_days=21, debug_dir=str(dbg))
    files = glob.glob(str(dbg / "run-*.json"))
    assert len(files) == 1
    data = json.loads(open(files[0], encoding="utf-8").read())
    assert "AI" in data["profiles"]
    assert data["profiles"]["AI"]["collected"] == 1


def test_run_auto_tracks_github_repos_from_final_topics(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    profiles = {"AI": {"github": {"topics": ["mcp"]}}}
    run(selected=["AI"], profiles=profiles, collectors=[FakeCollector()],
        client=FakeClient(), threshold=80, x_days=3, gh_days=21)
    # topic "T" (score 90) links to u1 = repo foo/bar -> auto-tracked; "weak" (50) not
    assert store.get_tracked_repos() == ["foo/bar"]


def test_run_snapshots_stars_for_auto_tracked_repo(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    profiles = {"AI": {"github": {"topics": ["mcp"]}}}
    run(selected=["AI"], profiles=profiles, collectors=[FakeCollector()],
        client=FakeClient(), threshold=80, x_days=3, gh_days=21)
    detail = store.get_tracked_detail()
    assert detail[0]["repo"] == "foo/bar"
    assert detail[0]["stars"] == 9          # first snapshot recorded at auto-track time


def test_run_returns_topics_alerts_warnings_shape(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    out = run(selected=["AI"], profiles={"AI": {"github": {"topics": ["mcp"]}}},
              collectors=[FakeCollector()], client=FakeClient(), threshold=80,
              x_days=3, gh_days=21)
    assert set(out) == {"topics", "alerts", "warnings"}


def test_run_surfaces_trending_alert_from_watchlist(tmp_path):
    from datetime import datetime, timezone, timedelta
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    now = datetime.now(timezone.utc)
    store.add_tracked_repo("hot/repo")
    store.record_stars("hot/repo", 100, at=(now - timedelta(days=2)).isoformat())
    store.record_stars("hot/repo", 800, at=now.isoformat())      # 350 stars/day
    out = run(selected=["AI"], profiles={"AI": {"github": {"topics": ["mcp"]}}},
              collectors=[FakeCollector()], client=FakeClient(), threshold=80,
              x_days=3, gh_days=21, min_velocity=50)
    assert [a["repo"] for a in out["alerts"]] == ["hot/repo"]


def test_run_drops_stagnant_tracked_repo(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    store.add_tracked_repo("stale/repo")
    store._set_last_growing("stale/repo", days_ago=30)
    run(selected=["AI"], profiles={"AI": {"github": {"topics": ["mcp"]}}},
        collectors=[FakeCollector()], client=FakeClient(), threshold=80,
        x_days=3, gh_days=21, stagnant_days=21)
    assert "stale/repo" not in store.get_tracked_repos()   # auto-dropped this run
    assert "foo/bar" in store.get_tracked_repos()          # fresh one still tracked


def test_run_raises_cancelled_when_cancel_event_set_before_start(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    event = threading.Event(); event.set()
    with pytest.raises(RunCancelled):
        run(selected=["AI"], profiles={"AI": {"github": {"topics": ["mcp"]}}},
            collectors=[FakeCollector()], client=FakeClient(), threshold=80,
            x_days=3, gh_days=21, cancel_event=event)
    assert store.get_recent_topics(days=1) == []   # nothing scored/stored


def test_run_cancels_after_collecting_before_scoring(tmp_path):
    # a collector that trips the cancel flag as a side-effect of collecting,
    # simulating "Stop" clicked while this profile's scrape was in flight
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    event = threading.Event()

    class TrippingCollector:
        source = "github"
        def collect(self, name, cfg):
            event.set()
            return [Signal.make(source="github", title="foo/bar", description="d",
                    url="u1", date=FRESH, profile=name, stars=9)]

    class SpyClient:
        calls = 0
        def make(self, messages):
            SpyClient.calls += 1
            return '{"scored":[],"groups":[]}'

    with pytest.raises(RunCancelled):
        run(selected=["AI"], profiles={"AI": {"github": {"topics": ["mcp"]}}},
            collectors=[TrippingCollector()], client=SpyClient(), threshold=80,
            x_days=3, gh_days=21, cancel_event=event)
    assert SpyClient.calls == 0                     # aborted before the LLM call
    assert store.get_recent_topics(days=1) == []


def test_run_without_cancel_event_is_unaffected(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    topics = run(selected=["AI"], profiles={"AI": {"github": {"topics": ["mcp"]}}},
                collectors=[FakeCollector()], client=FakeClient(), threshold=80,
                x_days=3, gh_days=21)["topics"]
    assert [t["title"] for t in topics] == ["T"]


def test_run_does_not_track_below_threshold_repos(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    # collector returns a repo that only ever scores below threshold
    class WeakCollector:
        source = "github"
        def collect(self, name, cfg):
            return [Signal.make(source="github", title="weak/repo", description="d",
                    url="uw", date=FRESH, profile=name, stars=1)]
    class WeakClient:
        def make(self, messages):
            return '{"topics":[{"title":"w","why":"w","score":50,"links":["uw"]}],"scored":[]}'
    run(selected=["AI"], profiles={"AI": {"github": {"topics": ["mcp"]}}},
        collectors=[WeakCollector()], client=WeakClient(), threshold=80,
        x_days=3, gh_days=21)
    assert store.get_tracked_repos() == []   # nothing reached final topics


# --- one signal, two profiles: it used to be scored and shown twice ----------------
# `seen` and `recent_titles` are read ONCE, before the profile loop, and the topics
# each profile inserts never joined them. Two profiles sharing an X list or a GitHub
# topic therefore paid for the same signal twice and put two identical cards in the
# feed. Measured on the 2026-08-16 run: 31 signals scored twice, one tweet that
# became a topic in both profiles.

class SharedCollector:
    """The same signal reaches every profile — a list both profiles subscribe to."""
    source = "github"
    def collect(self, name, cfg):
        return [Signal.make(source="github", title="foo/bar", description="d",
                            url="shared-url", date=FRESH, profile=name, stars=9)]


class CountingClient:
    def __init__(self):
        self.scored_batches = 0

    def make(self, messages):
        # `velocity` is in the SCORE payload only — the grouping call carries
        # "signals" too, so counting that word would count both passes.
        if '"velocity"' in messages[-1]["content"]:
            self.scored_batches += 1
        return ('{"scored":[{"i":0,"score":90,"reason":"r","title":"T"}],'
                '"groups":[]}')


def _two_profiles(tmp_path, client):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    return run(selected=["AI", "Crypto"],
               profiles={"AI": {"github": {"topics": ["mcp"]}},
                         "Crypto": {"github": {"topics": ["mcp"]}}},
               collectors=[SharedCollector()], client=client,
               threshold=80, x_days=3, gh_days=21)


def test_a_signal_shared_by_two_profiles_becomes_one_topic(tmp_path):
    out = _two_profiles(tmp_path, CountingClient())
    assert len(out["topics"]) == 1


def test_a_signal_shared_by_two_profiles_is_not_paid_for_twice(tmp_path):
    c = CountingClient()
    _two_profiles(tmp_path, c)
    assert c.scored_batches == 1


def test_the_shared_signal_is_stored_once(tmp_path):
    _two_profiles(tmp_path, CountingClient())
    assert len(store.get_recent_topics(days=60)) == 1


def test_the_run_hands_the_feed_window_to_both_halves(tmp_path, monkeypatch):
    """`cleanup_topics` deletes on the window, `seen_links` reads what survived. Widen
    one without the other and the fix is dead: the row is already gone by the time the
    seen set is built, or it is kept and then not looked for."""
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    seen = {}
    real_cleanup, real_links = store.cleanup_topics, store.seen_links
    monkeypatch.setattr(store, "cleanup_topics",
                        lambda **kw: seen.update(cleanup=kw) or real_cleanup(**kw))
    monkeypatch.setattr(store, "seen_links",
                        lambda days: seen.update(seen_days=days) or real_links(days))

    run(selected=["AI"], profiles={"AI": {"github": {"topics": ["mcp"]}}},
        collectors=[FakeCollector()], client=FakeClient(), threshold=80,
        x_days=3, gh_days=14, feed_days=30)

    assert seen["cleanup"] == {"x_days": 3, "gh_days": 14, "feed_days": 30}
    assert seen["seen_days"] == 30
