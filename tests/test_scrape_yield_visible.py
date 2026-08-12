"""How many tweets each X source actually gave, written into the debug log.

`X_MAX_TWEETS` is 150 and `X_MAX_SCROLLS` is 40, and the scroll loop stops at whichever
comes first — so raising the tweet cap raises the NET only while the scroll ceiling is
not the thing binding. Nothing recorded which one ended the loop, so the question could
only be answered by guessing. The log now carries the count per URL and the scrolls it
took, and the scrolls come back as None from anything that does not count them."""
import json

import topicparser.store as store
from topicparser.collectors.x import XCollector
from topicparser.models import Signal
from topicparser.pipeline import run


def tweet(i):
    return Signal.make(source="x", title="@a", description=f"t{i}",
                       url=f"https://x.com/a/status/{i}",
                       date="2026-08-19T09:00:00+00:00", profile="AI")


class Session:
    """Two URLs: the first runs into the scroll ceiling, the second runs dry."""
    yields = {"https://x.com/a": (3, 40), "https://x.com/i/lists/7": (1, 6)}

    def __init__(self, cookies_path, limit, max_scrolls): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass

    def scrape(self, url, profile):
        n, self.last_scrolls = self.yields[url]
        return [tweet(f"{url[-1]}{i}") for i in range(n)]


def _collector():
    return XCollector(cookies_path="c.json", session_factory=Session,
                      sleep=lambda s: None)


def test_the_collector_records_what_each_url_returned():
    c = _collector()
    c.collect("AI", {"x": {"accounts": ["a"], "lists": ["7"], "searches": []}})
    assert c.stats == [
        {"url": "https://x.com/a", "tweets": 3, "scrolls": 40},
        {"url": "https://x.com/i/lists/7", "tweets": 1, "scrolls": 6}]


def test_a_session_that_counts_nothing_reports_no_scrolls():
    class Quiet(Session):
        def scrape(self, url, profile):
            return [tweet(1)]
    c = XCollector(cookies_path="c.json", session_factory=Quiet,
                   sleep=lambda s: None)
    c.collect("AI", {"x": {"accounts": ["a"]}})
    assert c.stats == [{"url": "https://x.com/a", "tweets": 1, "scrolls": None}]


def test_the_debug_log_carries_it(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()

    class Client:
        def make(self, m):
            return '{"scored":[{"i":0,"score":90,"reason":"r","title":"T"}]}'

    run(selected=["AI"], profiles={"AI": {"x": {"accounts": ["a"], "lists": ["7"]}}},
        collectors=[_collector()], client=Client(), threshold=70,
        x_days=3000, gh_days=3000, prompt_loader=lambda n: "RULES",
        debug_dir=str(tmp_path / "debug"))

    f = sorted((tmp_path / "debug").glob("run-*.json"))[-1]
    d = json.load(open(f, encoding="utf-8"))
    assert d["profiles"]["AI"]["x_sources"][0]["tweets"] == 3
    assert d["profiles"]["AI"]["x_sources"][0]["scrolls"] == 40


def test_it_is_recorded_even_when_nothing_survives_the_prefilter(tmp_path):
    # a profile that scraped almost nothing is exactly when the per-URL numbers are
    # worth having, and that path never reaches the scoring block
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    run(selected=["AI"], profiles={"AI": {"x": {"accounts": ["a"], "lists": ["7"]}}},
        collectors=[_collector()], client=None, threshold=70,
        x_days=0, gh_days=0, prompt_loader=lambda n: "RULES",
        debug_dir=str(tmp_path / "debug"))
    f = sorted((tmp_path / "debug").glob("run-*.json"))[-1]
    d = json.load(open(f, encoding="utf-8"))
    assert d["profiles"]["AI"]["after_prefilter"] == 0
    assert [r["tweets"] for r in d["profiles"]["AI"]["x_sources"]] == [3, 1]


def test_a_profile_without_x_sources_does_not_inherit_the_previous_one():
    # ONE collector instance serves every profile in a run, and pipeline reads
    # `stats` off it per profile. Resetting after the early returns left the
    # previous profile's URLs in place, so a profile with no `x` section at all
    # reported a neighbour's tweets and scrolls as its own — worst exactly where
    # this was meant to help, on a profile that collected nothing.
    c = _collector()
    c.collect("AI", {"x": {"accounts": ["a"]}})
    assert c.stats

    c.collect("Crypto", {"github": {"topics": ["mcp"]}})     # no `x` key at all
    assert c.stats == []

    c.collect("Empty", {"x": {"accounts": [], "lists": [], "searches": []}})
    assert c.stats == []                                     # `x`, but no URLs
