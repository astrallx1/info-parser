"""A focused gate over the official-source posts, the same escape the tweets use.

Measured first: a lab's own blog is its marketing channel as much as its newsroom, and
the scorer waves through customer case studies, analyst awards and product how-tos
because they arrive first-party. Writing that rule into `_base.txt` DID hold the feeds
down (42 -> 25 of 69 over three replays a side) but dragged GitHub and X with it
(>=70 went 40/34/42 -> 33/30/25 per replay), because a shared prompt cannot be scoped.
A separate call can: GitHub and X signals are never sent, so they cannot be dropped.
"""
import pytest

from topicparser import ranker
from topicparser.models import Signal


def _sig(source, title, desc=""):
    return Signal.make(source=source, title=title, description=desc,
                       url=f"https://example.com/{title}", date="2026-08-11T00:00:00+00:00",
                       profile="AI")


class _Client:
    def __init__(self, reply="{}"):
        self.reply, self.seen = reply, []

    def make(self, messages):
        self.seen.append(messages)
        return self.reply


def test_only_feed_signals_are_sent():
    survivors = [_sig("github", "a/b"), _sig("feed", "Blog post"), _sig("x", "@someone")]
    client = _Client('{"drop": []}')

    ranker.gate_feeds(survivors, client, prompt="P")

    payload = client.seen[0][1]["content"]
    assert "Blog post" in payload
    assert "a/b" not in payload and "@someone" not in payload


def test_dropped_indices_point_at_the_survivor_list():
    survivors = [_sig("github", "a/b"), _sig("feed", "Case study"), _sig("feed", "Release")]
    client = _Client('{"drop": [1]}')

    assert ranker.gate_feeds(survivors, client, prompt="P") == {1}


def test_an_index_outside_the_feed_signals_drops_nothing():
    """The model answering with a GitHub signal's index must not remove it."""
    survivors = [_sig("github", "a/b"), _sig("feed", "Release")]
    client = _Client('{"drop": [0, 1]}')

    assert ranker.gate_feeds(survivors, client, prompt="P") == {1}


@pytest.mark.parametrize("reply", ["not json", "[]", '{"drop": "everything"}', ""])
def test_a_broken_reply_drops_nothing(reply):
    survivors = [_sig("feed", "Release")]
    assert ranker.gate_feeds(survivors, _Client(reply), prompt="P") == set()


def test_a_dead_api_drops_nothing():
    class Dead:
        def make(self, messages):
            raise RuntimeError("429")

    survivors = [_sig("feed", "Release")]
    assert ranker.gate_feeds(survivors, Dead(), prompt="P") == set()


def test_no_feed_signals_means_no_call_at_all():
    client = _Client('{"drop": [0]}')
    assert ranker.gate_feeds([_sig("github", "a/b")], client, prompt="P") == set()
    assert client.seen == []


def test_rank_skips_the_gate_when_no_prompt_is_wired():
    """Opt-in, exactly like the tweet gate: no prompt file, no extra paid call."""
    calls = []

    class C:
        def make(self, messages):
            calls.append(messages)
            return '{"scored": [{"i": 0, "score": 80, "title": "T", "reason": "R"}]}'

    ranker.rank([_sig("feed", "Release")], [], C(), system_prompt="S")
    assert all("posts" not in str(m[-1]["content"]) for m in calls)


def test_rank_runs_the_gate_before_clustering():
    """A gated post must not be able to pull a cluster together either."""
    seen = []

    class C:
        def make(self, messages):
            body = messages[-1]["content"]
            seen.append("feedgate" if '"posts"' in body else "other")
            if '"posts"' in body:
                return '{"drop": [0]}'
            return '{"scored": [{"i": 0, "score": 80, "title": "T", "reason": "R"}]}'

    out = ranker.rank([_sig("feed", "Case study")], [], C(), system_prompt="S",
                      feedgate_prompt="P")
    assert "feedgate" in seen
    assert out["topics"] == [], "the gated post produced no topic"
