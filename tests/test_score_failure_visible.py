"""A dead LLM used to produce a run that looked like a quiet news day.

`_score_pass` swallows a failed batch so one truncated reply cannot destroy fifteen
minutes of scraping — right call, but nothing was written down: with every batch
failing (an expired key, a 429 on each call) the gap-fill stops on its first empty
pass, no signal has a score, no signal survives, and the feed says "0 topics" with an
empty warning list. Every collector reports its own failures into the red banner; the
most expensive call in the run reported none."""
import topicparser.store as store
from topicparser import ranker
from topicparser.models import Signal
from topicparser.pipeline import run


def sig(i):
    return Signal.make(source="x", title="@a", description="d",
                       url=f"https://x.com/a/status/{i}",
                       date="2026-08-19T00:00:00Z", profile="AI")


class DeadClient:
    """Every call fails, the way an expired key or a rate limit does."""
    def make(self, messages):
        raise RuntimeError("429 rate limit")


class EmptyClient:
    """Answers, but never scores anything — valid JSON, no signals in it."""
    def make(self, messages):
        return '{"scored":[]}'


def test_rank_counts_the_batches_that_failed():
    out = ranker.rank([sig(1), sig(2)], [], DeadClient())
    assert out["failed_batches"] > 0
    assert out["topics"] == []


def test_failed_batches_is_zero_on_a_healthy_run():
    class Fine:
        def make(self, m):
            return '{"scored":[{"i":0,"score":90,"reason":"r","title":"T"}]}'
    out = ranker.rank([sig(1)], [], Fine())
    assert out["failed_batches"] == 0


class OneTweetCollector:
    source = "x"
    def collect(self, name, cfg):
        from datetime import datetime, timezone
        return [Signal.make(source="x", title="@a", description="d",
                            url="https://x.com/a/status/1",
                            date=datetime.now(timezone.utc).isoformat(), profile=name)]


def _run(tmp_path, client):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    return run(selected=["AI"], profiles={"AI": {"x": {"accounts": ["a"]}}},
               collectors=[OneTweetCollector()], client=client,
               threshold=70, x_days=3, gh_days=21,
               prompt_loader=lambda name: "REAL RULES")


def test_run_warns_when_scoring_calls_fail(tmp_path):
    out = _run(tmp_path, DeadClient())
    assert out["topics"] == []
    assert out["warnings"], "a dead scorer must not look like a quiet news day"


def test_run_warns_when_nothing_came_back_scored(tmp_path):
    # the model answered every time and scored nothing: no exception to count, and
    # the same empty feed at the end of it
    out = _run(tmp_path, EmptyClient())
    assert out["warnings"], "an empty score reply must not look like a quiet news day"


def test_run_is_quiet_when_scoring_works(tmp_path):
    class Fine:
        def make(self, m):
            return '{"scored":[{"i":0,"score":90,"reason":"r","title":"T"}]}'
    out = _run(tmp_path, Fine())
    assert out["warnings"] == []


# --- scored fine, nothing reached the bar ------------------------------------------
#
# The third silent shape, and the reachable one: `SCORE_THRESHOLD` may be set to 100
# from the Settings screen, while over 3430 signals the model has never gone above 90
# and hardly ever above 80. Both branches above miss it — no batch failed and `scored`
# is full — so the feed said "0 topics" with no warning after twelve minutes of
# scraping, which is exactly the quiet-news-day reading this file exists to prevent.


class LowScoreClient:
    def make(self, messages):
        return '{"scored":[{"i":0,"score":45,"reason":"r"}]}'


def test_run_warns_when_nothing_reached_the_threshold(tmp_path):
    out = _run(tmp_path, LowScoreClient())
    assert out["topics"] == []
    assert out["warnings"], "0 topics with every signal scored must say why"
    assert "45" in out["warnings"][0], "the message names the best score, so the reader can aim the knob"


def test_the_threshold_warning_is_silent_when_a_topic_survives(tmp_path):
    class Fine:
        def make(self, m):
            return '{"scored":[{"i":0,"score":90,"reason":"r","title":"T"}]}'
    assert _run(tmp_path, Fine())["warnings"] == []


def test_the_threshold_warning_does_not_fire_when_a_gate_did_the_killing(tmp_path):
    """A signal that CLEARED the bar and was then dropped by a gate is a different
    story, and telling the reader to lower the threshold would be wrong."""
    class Gated:
        def make(self, m):
            body = "".join(x.get("content", "") for x in m)
            if "drop" in body.lower():
                return '{"drop":[0]}'
            return '{"scored":[{"i":0,"score":90,"reason":"r","title":"T"}]}'
    out = run(selected=["AI"], profiles={"AI": {"x": {"accounts": ["a"]}}},
              collectors=[OneTweetCollector()], client=Gated(),
              threshold=70, x_days=3, gh_days=21,
              prompt_loader=lambda name: "REAL RULES",
              xgate_prompt_loader=lambda: "GATE")
    assert out["topics"] == []
    assert out["warnings"] == []
