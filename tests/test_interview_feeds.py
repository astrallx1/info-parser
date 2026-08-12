"""Podcast channels are not first-party sources, so the feed gate must not judge them.

`_feedgate.txt` exists for one question: is a lab talking about ITSELF? A conversation
on somebody else's podcast is not that, and the gate cannot tell from a title — it
killed nine real interviews in the 2026-08-29 run ("DHH: Future of Programming" on Lex
Fridman, "How Cursor Built One of AI's Fastest-Growing Companies" on a16z, Anima
Anandkumar on Latent Space). The channel is known from config, so scope it there rather
than teaching a text rule to recognise an interview.
"""
from topicparser import ranker
from topicparser.collectors.feeds import FeedCollector
from topicparser.models import Signal


def _sig(url, first_party=True):
    return Signal.make(source="feed", title="T", description="D", url=url,
                       date="2026-08-29T10:00:00Z", profile="AI",
                       first_party=first_party)


def test_gate_feeds_skips_signals_that_are_not_first_party():
    seen = {}

    class Client:
        def make(self, messages):
            seen["payload"] = messages
            return '{"drop": [0]}'

    lab = _sig("https://openai.com/index/thing")
    pod = _sig("https://www.youtube.com/watch?v=abc", first_party=False)
    drop = ranker.gate_feeds([lab, pod], Client(), prompt="p")
    assert 1 not in drop, "a podcast episode reached the first-party gate"
    body = str(seen["payload"])
    assert "v=abc" not in body, "the gate was even shown the podcast"


def test_gate_is_skipped_entirely_when_every_feed_signal_is_a_podcast():
    class Client:
        def make(self, messages):
            raise AssertionError("no first-party post to judge, so no call")

    assert ranker.gate_feeds([_sig("https://youtu.be/x", first_party=False)],
                             Client(), prompt="p") == set()


def test_collector_marks_interview_feeds_as_not_first_party():
    class Coll(FeedCollector):
        def _fetch(self, url):            # no network in tests
            return url.encode()

    seen = []

    def fake_parse(body, profile, limit=None):
        url = body.decode()
        seen.append(url)
        return [Signal.make(source="feed", title="t", description="d",
                            url=url + "#item", date="", profile=profile)]

    import topicparser.collectors.feeds as mod
    real = mod.parse_feed
    mod.parse_feed = fake_parse
    try:
        out = Coll().collect("AI", {"feeds": {"urls": ["https://openai.com/rss"],
                                              "interviews": ["https://yt/podcast"]}})
    finally:
        mod.parse_feed = real

    by = {s.url: s.first_party for s in out}
    assert by["https://openai.com/rss#item"] is True
    assert by["https://yt/podcast#item"] is False


def test_signal_defaults_to_first_party():
    # every existing caller builds one without the flag, and those are lab blogs
    assert Signal.make(source="feed", title="t", description="d", url="u",
                       date="", profile="AI").first_party is True


def test_a_profile_whose_only_source_is_interviews_can_run():
    # `_has_sources` decides whether a profile is dropped before the run starts. It
    # counted `feeds.urls` and not `feeds.interviews`, so a profile carrying only
    # podcasts read as empty and was refused with a message blaming the profile.
    from topicparser.api import _has_sources
    assert _has_sources({"feeds": {"interviews": ["https://yt/x"]}}) is True
    assert _has_sources({"feeds": {"urls": [], "interviews": []}}) is False


def test_the_ui_sends_interviews_and_the_picker_shows_them():
    """The picker is the ONLY way a source reaches a run: `run_parser` is handed a
    pruned config built from the ticked boxes, so a list the picker never renders is
    collected by nobody. `feeds.interviews` shipped in the yaml a day before the UI
    knew about it, and eleven channels were silently dead in the packaged app while
    every run from source used them."""
    import os
    ui = open(os.path.join(os.path.dirname(__file__), "..", "topicparser", "ui",
                           "index.html"), encoding="utf-8").read()
    assert "kind:'interviews'" in ui, "the picker has no row for interview feeds"
    assert "selection[profile].feeds.interviews.push" in ui, \
        "a ticked interview feed is not sent to run_parser"
    assert "(cfg.feeds||{}).interviews" in ui, "the picker reads no interview list"
    assert "field.interviews_label" in ui, "the profile editor cannot add one"
