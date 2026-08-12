"""X gate: a 4th, deliberately tiny LLM call that re-judges only the TWEETS that
survived scoring. The main score call carries the whole 280-line profile prompt over
~280 signals and the weak model never reaches the own-angle rules — someone's finished
opinion or a "look what I found" demo lands at 70+ run after run, even when named
verbatim in the prompt. Three prompt rewrites failed; a small focused call is the
pattern that already fixed clustering and cross-run dedup."""
import pytest
from topicparser.models import Signal
from topicparser.ranker import build_xgate_messages, parse_xgate, gate_tweets


def tw(author, text):
    return Signal.make(source="x", title=f"@{author}", description=text,
                       url=f"https://x.com/{author}/status/1", date="", profile="AI")


def gh(name):
    return Signal.make(source="github", title=name, description="d",
                       url=f"https://github.com/{name}", date="", profile="AI")


class Client:
    """Records the messages it was handed; replies with a canned string."""
    def __init__(self, reply='{"drop":[]}'):
        self.reply, self.calls = reply, []

    def make(self, messages):
        self.calls.append(messages)
        return self.reply


def test_only_tweets_are_sent_to_the_gate():
    import json
    c = Client()
    gate_tweets([gh("a/b"), tw("x", "hello"), gh("c/d")], c, "P")
    payload = json.loads(c.calls[0][1]["content"])
    assert [t["i"] for t in payload["tweets"]] == [1]      # survivor index, not 0
    assert payload["tweets"][0]["author"] == "@x"
    assert c.calls[0][0]["content"] == "P"                 # the gate prompt, not the profile one


def test_dropped_indices_come_back_as_survivor_indices():
    c = Client('{"drop":[1]}')
    assert gate_tweets([gh("a/b"), tw("x", "someone else's find"), tw("y", "news")],
                       c, "P") == {1}


def test_github_can_never_be_dropped():
    # the gate only ever judges tweets; a model naming a GitHub index is ignored
    c = Client('{"drop":[0,1]}')
    assert gate_tweets([gh("a/b"), tw("x", "t")], c, "P") == {1}


def test_no_tweets_means_no_call_at_all():
    c = Client('{"drop":[0]}')
    assert gate_tweets([gh("a/b"), gh("c/d")], c, "P") == set()
    assert c.calls == []              # no wasted call on a GitHub-only run


def test_empty_survivors():
    c = Client()
    assert gate_tweets([], c, "P") == set()
    assert c.calls == []


def test_broken_reply_drops_nothing():
    # same contract as parse_dedup: a topic must never be lost to a parse error
    for bad in ("not json", "[]", '{"oops":1}', ""):
        assert parse_xgate(bad) == set()


def test_out_of_range_indices_ignored():
    c = Client('{"drop":[99,-3,1]}')
    assert gate_tweets([gh("a/b"), tw("x", "t")], c, "P") == {1}


def test_llm_failure_drops_nothing():
    # the gate is an improvement, not a dependency: if the call blows up the run
    # keeps every topic rather than dying
    class Boom:
        def make(self, messages):
            raise RuntimeError("api down")
    assert gate_tweets([tw("x", "t")], Boom(), "P") == set()


def test_cancel_event_raises_before_the_call():
    import threading
    from topicparser.cancellation import RunCancelled
    ev = threading.Event(); ev.set()
    c = Client()
    with pytest.raises(RunCancelled):
        gate_tweets([tw("x", "t")], c, "P", cancel_event=ev)
    assert c.calls == []


def test_build_messages_carries_text_and_index():
    import json
    msgs = build_xgate_messages([(3, tw("somebody", "this creator just built..."))], "P")
    payload = json.loads(msgs[1]["content"])
    assert payload["tweets"] == [{"i": 3, "author": "@somebody",
                                  "text": "this creator just built..."}]


def test_rank_drops_gated_tweet_end_to_end():
    from topicparser import ranker

    class RankClient:
        """score -> xgate -> group, in call order."""
        def __init__(self): self.n = 0
        def make(self, messages):
            self.n += 1
            if self.n == 1:
                return ('{"scored":[{"i":0,"score":90,"reason":"r","title":"Keep"},'
                        '{"i":1,"score":80,"reason":"r","title":"Drop"}]}')
            if self.n == 2:
                return '{"drop":[1]}'          # the gate kills survivor #1
            return '{"groups":[],"stale":[]}'

    out = ranker.rank([tw("OpenAI", "new model"), tw("somebody", "look what I found")],
                      [], RankClient(), xgate_prompt="P")
    assert [t["title"] for t in out["topics"]] == ["Keep"]


def test_rank_without_xgate_prompt_makes_no_gate_call():
    # the gate is opt-in: no prompt wired (tests, or the file missing) -> old behaviour
    from topicparser import ranker

    class RankClient:
        def __init__(self): self.n = 0
        def make(self, messages):
            self.n += 1
            if self.n == 1:
                return '{"scored":[{"i":0,"score":90,"reason":"r","title":"Keep"}]}'
            return '{"groups":[],"stale":[]}'

    c = RankClient()
    out = ranker.rank([tw("OpenAI", "new model")], [], c)
    assert [t["title"] for t in out["topics"]] == ["Keep"]
    assert c.n == 2                    # score + group only, no gate call
