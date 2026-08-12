"""The debug log records every SCORE but never what a GATE threw away.

On the 2026-08-16 run one profile turned 26 signals at >=70 into 5 topics, with
eight tweets from ONE account about a single model release among the missing, and the log
could not say whether the tweet gate or the cross-run dedup did it, because neither
writes anything down. Clustering was ruled out only because its raw reply happened to
be stored. A run that costs money and fifteen minutes must not need a second run to
explain itself."""
from topicparser import ranker
from topicparser.models import Signal


def sig(url, source="x", title="@a"):
    return Signal.make(source=source, title=title, description="d", url=url,
                       date="2026-08-16T00:00:00Z", profile="AI")


class Scripted:
    def __init__(self, replies):
        self.replies = list(replies)

    def make(self, messages):
        return self.replies.pop(0) if self.replies else "{}"


SCORED_2 = ('{"scored":[{"i":0,"score":90,"reason":"r0","title":"T0"},'
            '{"i":1,"score":90,"reason":"r1","title":"T1"}]}')


def test_rank_reports_which_tweets_the_x_gate_dropped():
    c = Scripted([SCORED_2, '{"drop":[1]}', '{"groups":[]}'])
    out = ranker.rank([sig("https://x.com/a/status/1"), sig("https://x.com/b/status/2")],
                      [], c, xgate_prompt="gate")
    assert out["dropped"]["xgate"] == ["https://x.com/b/status/2"]


def test_rank_reports_which_feed_posts_the_feed_gate_dropped():
    c = Scripted([SCORED_2, '{"drop":[0]}', '{"groups":[]}'])
    out = ranker.rank([sig("https://openai.com/a", source="feed"),
                       sig("https://openai.com/b", source="feed")],
                      [], c, feedgate_prompt="gate")
    assert out["dropped"]["feedgate"] == ["https://openai.com/a"]


def test_rank_reports_which_topics_the_cross_run_dedup_dropped():
    c = Scripted([SCORED_2, '{"groups":[]}', '{"drop":[0]}'])
    out = ranker.rank([sig("https://x.com/a/status/1"), sig("https://x.com/b/status/2")],
                      ["an earlier topic"], c, dedup_prompt="dd")
    assert out["dropped"]["dedup"] == ["T0"]
    assert [t["title"] for t in out["topics"]] == ["T1"]


def test_dropped_is_present_and_empty_when_no_gate_runs():
    # the key always exists, so a reader never has to guess whether a gate was off
    # or simply dropped nothing.
    c = Scripted([SCORED_2, '{"groups":[]}'])
    out = ranker.rank([sig("https://x.com/a/status/1"), sig("https://x.com/b/status/2")], [], c)
    assert out["dropped"] == {"xgate": [], "feedgate": [], "dedup": []}


def test_a_failing_gate_records_no_drops():
    c = Scripted([SCORED_2, RuntimeError("429"), '{"groups":[]}'])

    class Boom(Scripted):
        def make(self, messages):
            r = self.replies.pop(0) if self.replies else "{}"
            if isinstance(r, Exception):
                raise r
            return r
    out = ranker.rank([sig("https://x.com/a/status/1"), sig("https://x.com/b/status/2")],
                      [], Boom([SCORED_2, RuntimeError("429"), '{"groups":[]}']),
                      xgate_prompt="gate")
    assert out["dropped"]["xgate"] == []
    assert len(out["topics"]) == 2


# --- and it has to reach the file, not just the return value ----------------------

def test_the_debug_log_records_what_each_gate_dropped(tmp_path):
    import json
    import topicparser.store as store
    from topicparser.pipeline import run
    from datetime import datetime, timedelta, timezone

    fresh = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ')

    class Col:
        source = "x"
        def collect(self, name, cfg):
            return [Signal.make(source="x", title="@a", description="d",
                                url="https://x.com/a/status/1", date=fresh, profile=name),
                    Signal.make(source="x", title="@b", description="d",
                                url="https://x.com/b/status/2", date=fresh, profile=name)]

    class Client:
        def __init__(self): self.n = 0
        def make(self, messages):
            self.n += 1
            if self.n == 1:
                return SCORED_2
            if self.n == 2:
                return '{"drop":[1]}'          # the X gate
            return '{"groups":[]}'

    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    debug_dir = tmp_path / "debug"
    run(selected=["AI"], profiles={"AI": {"x": {"accounts": ["a"]}}},
        collectors=[Col()], client=Client(), threshold=70, x_days=3, gh_days=21,
        xgate_prompt_loader=lambda: "gate", debug_dir=str(debug_dir))

    written = json.loads(next(debug_dir.glob("run-*.json")).read_text(encoding="utf-8"))
    assert written["profiles"]["AI"]["dropped"]["xgate"] == ["https://x.com/b/status/2"]
