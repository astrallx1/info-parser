"""Subjects you never cover, dropped in code rather than by prompt.

A cap written into the scoring prompt held on GitHub repos and leaked on tweets: two
tweets about a capped subject scored 70 and reached the feed, reproduced in three offline
replays. Moving the rule into `_xgate.txt` was measured too: it did not drop them and it
made the gate strictly harsher (kept 25/29/25 -> 18/17/18 of 49). So this is a code rule,
deterministic and free.

The narrow matching is deliberate. Half the signals that mention a model are multi-model
tools ("use any LLM: A, B, C") and are not about it at all, so dropping those would lose
real topics. `novabyte` below stands in for whatever you put in `OFF_INTEREST`, which
ships empty.
"""
from topicparser.prefilter import drop_off_interest
from topicparser.models import Signal


def sig(title="x", desc="", source="github"):
    return Signal.make(source=source, title=title, description=desc,
                       url=f"http://e/{title}{len(desc)}", date="", profile="AI")


TERMS = {"novabyte"}


def test_a_repo_named_after_the_subject_is_dropped():
    assert drop_off_interest([sig(title="acme/Novabyte-API")], TERMS) == []


def test_a_tweet_leading_with_the_subject_is_dropped():
    s = sig(title="@somebody", source="x",
            desc="Novabyte-V4-Flash shipped today. Same architecture as April.")
    assert drop_off_interest([s], TERMS) == []


def test_a_repo_built_around_the_subject_is_dropped():
    s = sig(title="acme/whale",
            desc="Blazingly fast, terminal-first AI coding agent for Novabyte.")
    assert drop_off_interest([s], TERMS) == []


def test_a_passing_mention_in_a_model_list_survives():
    """This is the whole reason the rule is not a plain substring match."""
    s = sig(title="acme/openproxy",
            desc="Universal provider proxy for any coding CLI: use any LLM "
                 "(Claude, Gemini, Grok, Novabyte, Ollama) with it.")
    assert drop_off_interest([s], TERMS) == [s]


def test_an_unrelated_signal_survives():
    s = sig(title="anthropic/claude", desc="A model by Anthropic.")
    assert drop_off_interest([s], TERMS) == [s]


def test_matching_ignores_case_and_punctuation_in_the_name():
    for name in ("novabyte-translation-studio", "Novabyte_tools", "NOVABYTE/api"):
        assert drop_off_interest([sig(title=name)], TERMS) == []


def test_no_terms_configured_changes_nothing():
    s = sig(title="acme/Novabyte-API")
    assert drop_off_interest([s], set()) == [s]


# --- the term is a WORD, not a substring ------------------------------------------
#
# The match ran over the raw string, so a term ate every longer word containing it:
# `grok` dropped `grokking-algorithms`, which is a book about algorithms. The loss is
# silent — prefilter runs before scoring, and until now nothing recorded what it
# removed, so a wrong drop left no trace in the run log or the feed.
#
# A repo name is `owner/repo` and full of separators, so the boundaries are the ones a
# name actually uses: `-`, `/`, `_`, `.` and whitespace. Word boundaries around
# whitespace alone would let `ai-agents` slip past the term `agents`, which just moves
# the error to the other side.


def test_a_term_inside_a_longer_word_is_not_a_match():
    assert drop_off_interest([sig(title="user/grokking-algorithms")], {"grok"})
    assert drop_off_interest([sig(desc="we tested grokking behaviour")], {"grok"})


def test_a_term_between_name_separators_still_matches():
    for title in ("xai/grok", "xai/grok-cli", "user/grok_tools", "dev/grok.py",
                  "someone/ai-grok-wrapper"):
        assert drop_off_interest([sig(title=title)], {"grok"}) == [], title


def test_a_hyphenated_name_matches_its_own_word():
    """`ai-agents` IS about agents — the separator rule has to cut both ways."""
    assert drop_off_interest([sig(title="someone/ai-agents")], {"agents"}) == []


def test_a_multi_word_term_still_works():
    assert drop_off_interest([sig(desc="a wrapper around gpt 4 vision")],
                             {"gpt 4"}) == []


# --- and it leaves a trace ---------------------------------------------------------


def test_the_dropped_signals_can_be_asked_for():
    """`prefilter` runs before scoring, so an off-interest drop costs no LLM call —
    and left NO record anywhere: not in the feed, not in `dropped`, only as a smaller
    `after_prefilter`. A wrong term was therefore invisible to the person who typed
    it. The caller can now collect what went."""
    gone = []
    kept = drop_off_interest([sig(title="xai/grok-cli"), sig(title="a/other")],
                             {"grok"}, dropped=gone.append)
    assert [s.title for s in kept] == ["a/other"]
    assert gone == ["xai/grok-cli"]


def test_collecting_the_drops_is_optional():
    assert drop_off_interest([sig(title="xai/grok-cli")], {"grok"}) == []


def test_the_run_log_records_what_the_code_filter_removed(tmp_path):
    """End to end: the key is always present, so "the filter was off" reads
    differently from "the filter dropped nothing" — the same contract the gate keys
    carry."""
    import json
    import topicparser.store as store
    from topicparser.pipeline import run

    class Collector:
        source = "github"
        def collect(self, name, cfg):
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()
            return [Signal.make(source="github", title="xai/grok-cli", description="d",
                                url="u1", date=now, profile=name),
                    Signal.make(source="github", title="user/grokking-algorithms",
                                description="a book about algorithms", url="u2",
                                date=now, profile=name)]

    class Client:
        def make(self, m):
            return '{"scored":[{"i":0,"score":90,"reason":"r","title":"T"}]}'

    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    debug = tmp_path / "debug"
    run(selected=["AI"], profiles={"AI": {"github": {"topics": ["mcp"]}}},
        collectors=[Collector()], client=Client(), threshold=70, x_days=3, gh_days=21,
        off_interest={"grok"}, debug_dir=str(debug),
        prompt_loader=lambda name: "RULES")

    log = json.loads(next(debug.glob("run-*.json")).read_text(encoding="utf-8"))
    dropped = log["profiles"]["AI"]["dropped"]
    assert dropped["off_interest"] == ["xai/grok-cli"]      # the book survived
