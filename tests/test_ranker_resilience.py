"""A run is expensive — ~15 minutes of X scraping plus every paid scoring call —
and NOTHING is persisted until `rank` returns. So a single failing LLM call late in
the pipeline used to throw all of it away. The gate already guarded itself; these
tests pin the same contract onto the two calls that did not: clustering and dedup
IMPROVE a run, they must never be able to destroy one."""
import pytest
from topicparser import ranker
from topicparser.models import Signal


def sig(url, source="github", title="a/b"):
    return Signal.make(source=source, title=title, description="d", url=url,
                       date="2026-07-30T00:00:00Z", profile="AI")


class ScriptedClient:
    """Returns canned replies in order; an entry that is an Exception is raised."""
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def make(self, messages):
        self.calls += 1
        r = self.replies.pop(0) if self.replies else "{}"
        if isinstance(r, Exception):
            raise r
        return r


SCORED_2 = ('{"scored":[{"i":0,"score":90,"reason":"r0","title":"T0"},'
            '{"i":1,"score":80,"reason":"r1","title":"T1"}]}')


def test_rank_survives_a_failing_group_call():
    # the group call dies (rate limit / network blip) -> fall back to all-singletons,
    # exactly like a broken-JSON reply already does. The run's work is kept.
    c = ScriptedClient([SCORED_2, RuntimeError("openai 429 rate limit")])
    out = ranker.rank([sig("https://github.com/a/b"), sig("https://github.com/c/d")],
                      [], c)
    assert [t["title"] for t in out["topics"]] == ["T0", "T1"]


def test_rank_survives_a_failing_dedup_call():
    # same contract for the 4th call: a dead dedup drops NOTHING.
    c = ScriptedClient([SCORED_2, '{"groups":[],"stale":[]}',
                        RuntimeError("connection reset")])
    out = ranker.rank([sig("https://github.com/a/b"), sig("https://github.com/c/d")],
                      ["Some earlier topic"], c)
    assert len(out["topics"]) == 2


def test_dedup_shown_returns_all_topics_when_the_call_fails():
    topics = [{"title": "A"}, {"title": "B"}]
    c = ScriptedClient([RuntimeError("boom")])
    assert ranker.dedup_shown(topics, ["earlier"], c) == topics


def test_the_new_guards_do_not_swallow_cancellation():
    # The guards catch Exception, and RunCancelled IS one — Stop must still get out
    # rather than being silently downgraded to "no clusters found".
    from topicparser.cancellation import RunCancelled
    c = ScriptedClient([SCORED_2, RunCancelled()])
    with pytest.raises(RunCancelled):
        ranker.rank([sig("https://github.com/a/b"), sig("https://github.com/c/d")],
                    [], c)


# --- PASS 1 was the last unguarded call, and the most expensive one ---------------
# Scoring is where the money goes: 15 minutes of scraping and every paid batch before
# this one are thrown away if a single reply comes back truncated. The gap-fill that
# already exists is exactly the recovery path, so a dead batch only has to fall
# through to it instead of taking the run down.

SCORED_0 = '{"scored":[{"i":0,"score":90,"reason":"r0","title":"T0"}]}'


def test_a_failing_score_batch_does_not_destroy_the_batches_before_it():
    c = ScriptedClient([SCORED_0, RuntimeError("openai 429 rate limit")])
    out = ranker.rank([sig("https://github.com/a/b"), sig("https://github.com/c/d")],
                      [], c, batch_size=1)
    assert [t["title"] for t in out["topics"]] == ["T0"]


def test_a_truncated_score_reply_does_not_destroy_the_run():
    # the realistic failure: a 120-signal batch hits the output-token ceiling and the
    # JSON stops mid-object.
    truncated = '{"scored":[{"i":0,"score":90,"reason":"r0","tit'
    c = ScriptedClient([SCORED_0, truncated])
    out = ranker.rank([sig("https://github.com/a/b"), sig("https://github.com/c/d")],
                      [], c, batch_size=1)
    assert [t["title"] for t in out["topics"]] == ["T0"]


def test_a_dead_score_batch_is_re_asked_by_the_gap_fill():
    # the batch that died is not lost, it is simply unscored — and the gap-fill pass
    # that already exists for omitted signals picks it up on the next round.
    c = ScriptedClient([SCORED_0, RuntimeError("boom"),
                        '{"scored":[{"i":0,"score":80,"reason":"r1","title":"T1"}]}'])
    out = ranker.rank([sig("https://github.com/a/b"), sig("https://github.com/c/d")],
                      [], c, batch_size=1)
    assert sorted(t["title"] for t in out["topics"]) == ["T0", "T1"]


def test_score_cancellation_still_gets_out():
    from topicparser.cancellation import RunCancelled
    c = ScriptedClient([RunCancelled()])
    with pytest.raises(RunCancelled):
        ranker.rank([sig("https://github.com/a/b")], [], c, batch_size=1)


# --- parse_scored used to trust every field the model sent ------------------------

def test_parse_scored_skips_entries_whose_score_is_not_a_number():
    # `int(None)` and `int("high")` both raise, and this ran with no guard at all.
    raw = ('{"scored":[{"i":0,"score":null},{"i":1,"score":"high"},'
           '{"i":2,"score":85,"reason":"r","title":"T"}]}')
    assert [s["i"] for s in ranker.parse_scored(raw)] == [2]


def test_parse_scored_clamps_a_score_to_its_range():
    raw = '{"scored":[{"i":0,"score":9999},{"i":1,"score":-40}]}'
    assert [s["score"] for s in ranker.parse_scored(raw)] == [100, 0]


def test_parse_scored_skips_an_unusable_index():
    raw = '{"scored":[{"i":"x","score":90},{"i":1,"score":90}]}'
    assert [s["i"] for s in ranker.parse_scored(raw)] == [1]


def test_parse_scored_skips_an_entry_with_no_score_at_all():
    """A missing `score` became 0, which is a VERDICT — the signal counted as scored,
    the gap-fill never re-asked it, and it was dead for the run. The whole retry
    machinery exists against a model that omits things; it must not have a hole at the
    one place the model omits a FIELD rather than a whole entry."""
    raw = '{"scored":[{"i":0,"reason":"junk"},{"i":1,"score":0},{"i":2,"score":45}]}'
    assert [(s["i"], s["score"]) for s in ranker.parse_scored(raw)] == [(1, 0), (2, 45)]


def test_a_signal_the_model_never_scored_is_counted(monkeypatch):
    """`failed_batches` counts a dead call; nothing counted a signal the model simply
    left out of a reply that parsed. After the gap-fill has given up they are the
    signals in the log with a null score, and the count says how many without a grep."""
    # scores the first signal, then keeps answering with nothing for the gap-fill
    c = ScriptedClient(['{"scored":[{"i":0,"score":80,"title":"T","reason":"r"}]}',
                        '{"scored":[]}',
                        '{"groups":[],"stale":[]}', '{"drop":[]}'])
    signals = [sig("https://github.com/a/one"), sig("https://github.com/a/two")]
    out = ranker.rank(signals, [], c, system_prompt="RULES")
    assert out["unscored"] == 1
    assert out["failed_batches"] == 0
