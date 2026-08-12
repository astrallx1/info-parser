import json
import threading
from topicparser.models import Signal
from topicparser.cancellation import RunCancelled
from topicparser.ranker import (build_messages, build_group_messages,
                                parse_groups, parse_scored, parse_dedup,
                                dedup_shown, rank)

def _sig(url, title="foo/bar"):
    return Signal.make(source="github", title=title, description="d",
                       url=url, date="2026-07-07T00:00:00Z", profile="AI", stars=10)

def test_build_messages_includes_signals_and_recent_titles():
    msgs = build_messages([_sig("u1")], recent_titles=["Claude 5 released"])
    blob = json.dumps(msgs)
    assert "u1" in blob and "Claude 5 released" in blob

def test_build_messages_uses_given_system_prompt():
    msgs = build_messages([_sig("u1")], recent_titles=[], system_prompt="MY RULES")
    assert msgs[0]["role"] == "system" and "MY RULES" in msgs[0]["content"]

def test_build_messages_numbers_signals():
    msgs = build_messages([_sig("u1"), _sig("u2")], recent_titles=[])
    payload = json.loads(msgs[1]["content"])
    assert [s["i"] for s in payload["signals"]] == [0, 1]

def test_parse_scored_reads_per_signal_scores():
    raw = json.dumps({"scored": [{"i": 0, "score": 90, "reason": "on niche"},
                                 {"i": 1, "score": 10, "reason": "ad"}]})
    scored = parse_scored(raw)
    assert [(s["i"], s["score"]) for s in scored] == [(0, 90), (1, 10)]

def test_parse_scored_reads_optional_title():
    raw = json.dumps({"scored": [
        {"i": 0, "score": 90, "reason": "r", "title": "GPT-Red launched"},
        {"i": 1, "score": 10, "reason": "ad"}]})
    scored = parse_scored(raw)
    assert scored[0]["title"] == "GPT-Red launched"
    assert scored[1]["title"] == ""

def test_parse_scored_missing_key_is_empty():
    assert parse_scored(json.dumps({"topics": []})) == []


def test_parse_groups_reads_clusters_and_stale():
    raw = json.dumps({"groups": [{"indices": [0, 2], "title": "T", "why": "W"}],
                      "stale": [5]})
    out = parse_groups(raw)
    assert out["groups"] == [{"indices": [0, 2], "title": "T", "why": "W"}]
    assert out["stale"] == [5]

def test_parse_groups_tolerates_garbage():
    # coverage must never depend on the LLM behaving: bad JSON -> no groups.
    assert parse_groups("not json at all") == {"groups": [], "stale": []}
    assert parse_groups(json.dumps({})) == {"groups": [], "stale": []}


def _score_reply(entries):
    return json.dumps({"scored": entries})

def test_rank_merges_grouped_survivors_and_singles_out_the_rest():
    sigs = [_sig("u0", "a/a"), _sig("u1", "b/b"), _sig("u2", "c/c")]
    class ScriptClient:
        def __init__(self): self.calls = 0
        def make(self, messages):
            self.calls += 1
            if self.calls == 1:   # scoring: all three survive, each with a title
                return _score_reply([
                    {"i": 0, "score": 90, "reason": "r0", "title": "T0"},
                    {"i": 1, "score": 80, "reason": "r1", "title": "T1"},
                    {"i": 2, "score": 75, "reason": "r2", "title": "T2"}])
            # grouping: u0+u2 are one story; u1 is not mentioned
            return json.dumps({"groups": [
                {"indices": [0, 2], "title": "Same story", "why": "W"}]})
    out = rank(sigs, recent_titles=[], client=ScriptClient())
    topics = out["topics"]
    assert len(topics) == 2                                   # merged + singleton
    merged = next(t for t in topics if len(t["links"]) == 2)
    single = next(t for t in topics if len(t["links"]) == 1)
    assert merged["links"] == ["u0", "u2"]
    assert merged["title"] == "Same story"
    assert merged["score"] == 90                              # max of the cluster
    assert single["links"] == ["u1"]
    assert single["title"] == "T1"                            # pass-1 title
    assert single["why"] == "r1"                              # pass-1 reason

def test_rank_topic_carries_repo_meta():
    # feed cards show stars + created + last-modified; a topic must carry them
    # through from its GitHub signal (they used to be dropped at assembly)
    s = Signal.make(source="github", title="owner/repo", description="d",
                    url="u0", date="2026-07-18T00:00:00Z", profile="AI",
                    stars=1234, created="2026-05-01T00:00:00Z")
    class C:
        def __init__(self): self.calls = 0
        def make(self, m):
            self.calls += 1
            if self.calls == 1:
                return _score_reply([{"i": 0, "score": 90, "reason": "r", "title": "T"}])
            return json.dumps({"groups": []})
    t = rank([s], recent_titles=[], client=C())["topics"][0]
    assert t["stars"] == 1234
    assert t["created"] == "2026-05-01T00:00:00Z"
    assert t["updated"] == "2026-07-18T00:00:00Z"       # pushed_at


def test_rank_covers_everything_when_group_call_returns_garbage():
    # THE guarantee: assembly is code, so even a useless grouping reply
    # still yields one topic per survivor.
    sigs = [_sig("u0"), _sig("u1")]
    class ScriptClient:
        def __init__(self): self.calls = 0
        def make(self, messages):
            self.calls += 1
            if self.calls == 1:
                return _score_reply([{"i": 0, "score": 90, "reason": "a", "title": "TA"},
                                     {"i": 1, "score": 75, "reason": "b", "title": "TB"}])
            return "oops, no json today"
    out = rank(sigs, recent_titles=[], client=ScriptClient())
    assert sorted(t["links"][0] for t in out["topics"]) == ["u0", "u1"]

def test_rank_singleton_title_falls_back_to_signal_title():
    sigs = [_sig("u0", "owner/repo")]
    class ScriptClient:
        def __init__(self): self.calls = 0
        def make(self, messages):
            self.calls += 1
            if self.calls == 1:   # scorer "forgot" the title
                return _score_reply([{"i": 0, "score": 90, "reason": "r"}])
            return json.dumps({"groups": []})
    out = rank(sigs, recent_titles=[], client=ScriptClient())
    assert out["topics"][0]["title"] == "owner/repo"

def test_rank_ignores_bogus_group_indices_and_reused_ones():
    sigs = [_sig("u0"), _sig("u1"), _sig("u2")]
    class ScriptClient:
        def __init__(self): self.calls = 0
        def make(self, messages):
            self.calls += 1
            if self.calls == 1:
                return _score_reply([{"i": 0, "score": 90, "reason": "a", "title": "TA"},
                                     {"i": 1, "score": 80, "reason": "b", "title": "TB"},
                                     {"i": 2, "score": 75, "reason": "c", "title": "TC"}])
            return json.dumps({"groups": [
                {"indices": [0, 1], "title": "G1", "why": "W"},
                {"indices": [1, 2, 99], "title": "G2", "why": "W"}]})   # 1 reused, 99 bogus
    out = rank(sigs, recent_titles=[], client=ScriptClient())
    # G1 takes u0+u1; G2 collapses to just u2 -> not a real cluster -> u2 singleton
    links = sorted(tuple(t["links"]) for t in out["topics"])
    assert links == [("u0", "u1"), ("u2",)]

def test_rank_rejects_cluster_of_different_repos():
    # user's hard rule: different repos are ALWAYS different stories — an LLM
    # "ecosystem" cluster of several repos is a category mix, not a story.
    sigs = [Signal.make(source="github", title="a/one", description="d",
                        url="https://github.com/a/one", date="2026-07-07T00:00:00Z",
                        profile="AI"),
            Signal.make(source="github", title="b/two", description="d",
                        url="https://github.com/b/two", date="2026-07-07T00:00:00Z",
                        profile="AI")]
    class ScriptClient:
        def __init__(self): self.calls = 0
        def make(self, messages):
            self.calls += 1
            if self.calls == 1:
                return _score_reply([{"i": 0, "score": 90, "reason": "a", "title": "TA"},
                                     {"i": 1, "score": 80, "reason": "b", "title": "TB"}])
            return json.dumps({"groups": [
                {"indices": [0, 1], "title": "Ecosystem", "why": "W"}]})
    out = rank(sigs, recent_titles=[], client=ScriptClient())
    assert sorted(len(t["links"]) for t in out["topics"]) == [1, 1]   # split back up

def test_rank_allows_cluster_of_one_repo_plus_tweets():
    # legit same-story cluster: ONE repo + a tweet talking about that repo.
    sigs = [Signal.make(source="github", title="a/one", description="d",
                        url="https://github.com/a/one", date="2026-07-07T00:00:00Z",
                        profile="AI"),
            Signal.make(source="x", title="@dev", description="a/one is great",
                        url="https://x.com/dev/status/1", date="2026-07-07T00:00:00Z",
                        profile="AI")]
    class ScriptClient:
        def __init__(self): self.calls = 0
        def make(self, messages):
            self.calls += 1
            if self.calls == 1:
                return _score_reply([{"i": 0, "score": 90, "reason": "a", "title": "TA"},
                                     {"i": 1, "score": 80, "reason": "b", "title": "TB"}])
            return json.dumps({"groups": [
                {"indices": [0, 1], "title": "One story", "why": "W"}]})
    out = rank(sigs, recent_titles=[], client=ScriptClient())
    assert len(out["topics"]) == 1 and len(out["topics"][0]["links"]) == 2

def test_rank_drops_stale_survivors():
    sigs = [_sig("u0"), _sig("u1")]
    class ScriptClient:
        def __init__(self): self.calls = 0
        def make(self, messages):
            self.calls += 1
            if self.calls == 1:
                return _score_reply([{"i": 0, "score": 90, "reason": "a", "title": "TA"},
                                     {"i": 1, "score": 80, "reason": "b", "title": "TB"}])
            return json.dumps({"groups": [], "stale": [1]})   # u1 already shown
    out = rank(sigs, recent_titles=[], client=ScriptClient())
    assert [t["links"][0] for t in out["topics"]] == ["u0"]

def test_rank_group_call_uses_group_prompt_and_carries_scores():
    seen = {}
    sigs = [_sig("u0"), _sig("u1")]
    class ScriptClient:
        def __init__(self): self.calls = 0
        def make(self, messages):
            self.calls += 1
            if self.calls == 1:
                return _score_reply([{"i": 0, "score": 90, "reason": "a", "title": "TA"},
                                     {"i": 1, "score": 75, "reason": "b", "title": "TB"}])
            if self.calls == 2:               # the grouping call (call 3 is dedup)
                seen["sys"] = messages[0]["content"]
                seen["payload"] = json.loads(messages[1]["content"])
                return json.dumps({"groups": []})
            return json.dumps({"drop": []})   # dedup call — drop nothing
    rank(sigs, recent_titles=["Old theme"], client=ScriptClient(),
         system_prompt="SCORING RULES", group_prompt="GROUPING RULES")
    assert seen["sys"] == "GROUPING RULES"
    assert [s["score"] for s in seen["payload"]["signals"]] == [90, 75]
    assert seen["payload"]["already_shown_themes"] == ["Old theme"]

def test_rank_keep_defaults_to_70():
    seen = {}
    sigs = [_sig("u0"), _sig("u1")]
    class ScriptClient:
        def __init__(self): self.calls = 0
        def make(self, messages):
            self.calls += 1
            if self.calls == 1:
                return _score_reply([{"i": 0, "score": 70, "reason": "a", "title": "TA"},
                                     {"i": 1, "score": 69, "reason": "b", "title": "TB"}])
            seen["payload"] = json.loads(messages[1]["content"])
            return json.dumps({"groups": []})
    rank(sigs, recent_titles=[], client=ScriptClient())
    assert [s["url"] for s in seen["payload"]["signals"]] == ["u0"]

def test_rank_no_survivors_skips_group_call():
    class OneCall:
        def __init__(self): self.calls = 0
        def make(self, messages):
            self.calls += 1
            return _score_reply([{"i": 0, "score": 20, "reason": "ad"}])
    c = OneCall()
    out = rank([_sig("u0")], recent_titles=[], client=c)
    assert c.calls == 1 and out["topics"] == []

def test_rank_gap_fills_signals_the_scorer_dropped():
    # the weak model output-fatigues and OMITS a signal from a long scoring reply.
    # rank must re-ask the missing one (in a smaller batch) instead of silently
    # dropping it — the same coverage guarantee grouping already has.
    sigs = [_sig("u0", "a/a"), _sig("u1", "b/b"), _sig("u2", "c/c")]
    class ScriptClient:
        def __init__(self): self.calls = 0
        def make(self, messages):
            self.calls += 1
            if self.calls == 1:   # PASS 1 omits i=1 (truncated reply)
                return _score_reply([{"i": 0, "score": 90, "reason": "r0", "title": "T0"},
                                     {"i": 2, "score": 75, "reason": "r2", "title": "T2"}])
            if self.calls == 2:   # gap-fill: re-ask sends just [u1] -> local index 0
                return _score_reply([{"i": 0, "score": 80, "reason": "r1", "title": "T1"}])
            return json.dumps({"groups": []})   # grouping
    c = ScriptClient()
    out = rank(sigs, recent_titles=[], client=c, keep=70)
    # every signal ends up scored, none dropped
    assert sorted((s["i"], s["score"]) for s in out["scored"]) == [(0, 90), (1, 80), (2, 75)]
    # the re-asked signal survived into a topic
    assert sorted(t["links"][0] for t in out["topics"]) == ["u0", "u1", "u2"]


def test_rank_gap_fill_is_bounded():
    # if the scorer NEVER returns a signal, rank must give up after a few tries,
    # not loop forever.
    sigs = [_sig("u0")]
    class NeverScores:
        def __init__(self): self.calls = 0
        def make(self, messages):
            self.calls += 1
            return _score_reply([])          # always omits everything
    c = NeverScores()
    out = rank(sigs, recent_titles=[], client=c, keep=70)
    assert c.calls <= 3                        # 1 initial + <=2 gap-fill retries
    assert out["topics"] == []                 # nothing scored -> no survivors


def test_rank_two_pass_on_big_day():
    sigs = [_sig("u0"), _sig("u1"), _sig("u2")]
    class ScriptClient:
        def __init__(self): self.calls = 0
        def make(self, messages):
            self.calls += 1
            if self.calls == 1:    # PASS 1, batch [u0, u1]
                return _score_reply([{"i": 0, "score": 90, "reason": "a", "title": "TA"},
                                     {"i": 1, "score": 40, "reason": "b"}])
            if self.calls == 2:    # PASS 1, batch [u2]
                return _score_reply([{"i": 0, "score": 80, "reason": "c", "title": "TC"}])
            return json.dumps({"groups": []})   # PASS 2 over survivors [u0, u2]
    c = ScriptClient()
    out = rank(sigs, recent_titles=[], client=c, batch_size=2, keep=60)
    assert c.calls == 3                                    # 2 score batches + 1 grouping
    assert sorted(t["links"][0] for t in out["topics"]) == ["u0", "u2"]
    # every signal is scored, indexed globally
    assert sorted((s["i"], s["score"]) for s in out["scored"]) == [(0, 90), (1, 40), (2, 80)]


def test_rank_raises_when_cancelled_before_scoring():
    # Stop pressed before ranking starts -> no LLM call is wasted
    ev = threading.Event(); ev.set()
    class Client:
        def __init__(self): self.calls = 0
        def make(self, messages): self.calls += 1; return _score_reply([])
    c = Client()
    try:
        rank([_sig("u0")], recent_titles=[], client=c, cancel_event=ev)
        assert False, "expected RunCancelled"
    except RunCancelled:
        pass
    assert c.calls == 0


def test_rank_cancels_between_score_batches():
    # Stop pressed during the LLM phase -> the run stops at the next batch,
    # it does not grind through every remaining batch + the grouping call
    ev = threading.Event()
    sigs = [_sig("u0"), _sig("u1"), _sig("u2")]
    class Client:
        def __init__(self): self.calls = 0
        def make(self, messages):
            self.calls += 1
            ev.set()   # user hits Stop right after the first batch scores
            return _score_reply([{"i": 0, "score": 90, "reason": "a", "title": "T"}])
    c = Client()
    try:
        rank(sigs, recent_titles=[], client=c, batch_size=1, cancel_event=ev)
        assert False, "expected RunCancelled"
    except RunCancelled:
        pass
    assert c.calls == 1   # stopped after the first batch, no grouping call


# --- cross-run story dedup: a separate focused call over the assembled topics ---

def test_parse_dedup_reads_drop_indices():
    assert parse_dedup(json.dumps({"drop": [0, 2]})) == {0, 2}

def test_parse_dedup_tolerates_garbage():
    # a broken reply must drop NOTHING (never lose a genuine topic to a parse error)
    assert parse_dedup("not json at all") == set()
    assert parse_dedup(json.dumps({"nope": 1})) == set()

def test_dedup_shown_drops_flagged_topics():
    topics = [{"title": "Kimi K3 is strong", "links": ["u0"]},
              {"title": "Brand new tool X", "links": ["u1"]}]
    class C:
        def make(self, messages): return json.dumps({"drop": [0]})   # first already shown
    out = dedup_shown(topics, ["Kimi K3 beats GPT"], client=C(), prompt=None)
    assert [t["title"] for t in out] == ["Brand new tool X"]

def test_dedup_shown_skips_call_when_nothing_shown():
    topics = [{"title": "T", "links": ["u0"]}]
    class C:
        def __init__(self): self.calls = 0
        def make(self, messages): self.calls += 1; return json.dumps({"drop": [0]})
    c = C()
    out = dedup_shown(topics, [], client=c, prompt=None)   # empty recent -> no call
    assert c.calls == 0 and out == topics

def test_rank_drops_already_shown_topic_via_dedup_call():
    # end to end: a survivor whose story was shown in a PRIOR run is dropped by the
    # dedicated dedup call even though same-run clustering left it a singleton.
    sigs = [_sig("u0", "a/a"), _sig("u1", "b/b")]
    class ScriptClient:
        def __init__(self): self.calls = 0
        def make(self, messages):
            self.calls += 1
            if self.calls == 1:
                return _score_reply([{"i": 0, "score": 90, "reason": "r0", "title": "Kimi K3 news"},
                                     {"i": 1, "score": 80, "reason": "r1", "title": "Fresh thing"}])
            if self.calls == 2:
                return json.dumps({"groups": []})            # no same-run clusters
            return json.dumps({"drop": [0]})                 # dedup: topic 0 already shown
    out = rank(sigs, recent_titles=["Kimi K3 already covered"], client=ScriptClient())
    assert [t["links"][0] for t in out["topics"]] == ["u1"]

def test_rank_skips_dedup_when_nothing_shown():
    # no prior topics -> no dedup call is made (saves cost)
    sigs = [_sig("u0")]
    class ScriptClient:
        def __init__(self): self.calls = 0
        def make(self, messages):
            self.calls += 1
            if self.calls == 1:
                return _score_reply([{"i": 0, "score": 90, "reason": "r", "title": "T"}])
            return json.dumps({"groups": []})
    c = ScriptClient()
    rank(sigs, recent_titles=[], client=c)
    assert c.calls == 2          # score + group only, no dedup
