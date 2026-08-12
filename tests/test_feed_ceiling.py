"""C1 — the cheapest source had the tightest ceiling, and nobody could see it.

`FeedCollector.DEFAULT_LIMIT = 25` was hardcoded in `feeds.py` and declared NOWHERE
else: not in `.env.example`, not in `KNOBS`, and `main.build_collectors` built
`FeedCollector()` with no arguments at all, so there was not even a place to put a
value. Two runs and a repackage went into widening the most expensive source (X, 40 ->
80 scrolls) while one HTTP GET with no browser and no cookies sat at 25.

**Whether it BINDS could not be read from the log**, which is the real defect: the cap
applies inside `parse_feed`, BEFORE the freshness filter, and the debug log only holds
what survived that filter (max ever seen: 19). So a feed that was truncated at 25 and
then aged down to 19 reads exactly like a feed that published 19.

The number stays 25 here on purpose. This declares it and makes it VISIBLE; changing
it is a net-width decision, and widening the net mid-baseline changes batch composition
and therefore the scores themselves.
"""
import inspect
import os
import re

import pytest

from topicparser import config, settings
from topicparser.collectors import feeds
from topicparser.collectors.feeds import FeedCollector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_EXAMPLE = os.path.join(ROOT, ".env.example")


def _main_fallback(name):
    with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
        found = dict(re.findall(r'config\.env_num\("([A-Z_]+)",\s*([0-9.]+)', f.read()))
    return found.get(name)


def test_the_ceiling_is_documented_in_env_example():
    documented = settings.read_env(ENV_EXAMPLE)
    assert "FEED_MAX_ITEMS" in documented, "the feed ceiling is still undeclared"
    assert int(documented["FEED_MAX_ITEMS"]) == feeds.DEFAULT_LIMIT


def test_main_wires_the_ceiling_with_the_same_fallback():
    """`FeedCollector()` took no arguments, so an `.env` value had nowhere to land."""
    fallback = _main_fallback("FEED_MAX_ITEMS")
    assert fallback is not None, "main.py never reads FEED_MAX_ITEMS"
    assert int(float(fallback)) == feeds.DEFAULT_LIMIT


def test_the_collector_signature_is_the_third_copy():
    assert inspect.signature(FeedCollector.__init__).parameters["limit"].default \
        == feeds.DEFAULT_LIMIT


def test_the_limit_still_applies_per_feed():
    """Declaring it must not stop it working."""
    items = "".join(f"<item><title>t{i}</title><link>https://e.dev/{i}</link>"
                    f"<pubDate>Mon, 01 Sep 2026 10:00:00 GMT</pubDate></item>"
                    for i in range(40))
    xml = f"<rss><channel>{items}</channel></rss>".encode()
    assert len(feeds.parse_feed(xml, "AI", limit=5)) == 5


# --- the visibility half: what each feed actually yielded -------------------------

def _rss(n, host="e.dev"):
    items = "".join(f"<item><title>t{i}</title><link>https://{host}/{i}</link>"
                    f"<pubDate>Mon, 01 Sep 2026 10:00:00 GMT</pubDate></item>"
                    for i in range(n))
    return f"<rss><channel>{items}</channel></rss>".encode()


def _collector(pages, limit=25):
    col = FeedCollector(limit=limit)
    col._fetch = lambda url: pages[url]
    return col


def test_each_feed_reports_what_it_yielded():
    """Mirrors `x_sources`, and for the same reason: a cut nobody can see is a cut
    nobody can tune. `items` is counted BEFORE the freshness filter, which is the
    whole point — that is the only place the ceiling is observable."""
    pages = {"https://a.dev/f.xml": _rss(30, "a.dev"),
             "https://b.dev/p.xml": _rss(4, "b.dev")}
    col = _collector(pages, limit=25)

    col.collect("AI", {"feeds": {"urls": ["https://a.dev/f.xml"],
                                 "interviews": ["https://b.dev/p.xml"]}})

    stats = {s["url"]: s for s in col.stats}
    assert stats["https://a.dev/f.xml"]["items"] == 25, "a truncated feed looks untouched"
    assert stats["https://a.dev/f.xml"]["capped"] is True
    assert stats["https://b.dev/p.xml"]["items"] == 4
    assert stats["https://b.dev/p.xml"]["capped"] is False
    assert stats["https://b.dev/p.xml"]["first_party"] is False


def test_a_skipped_feed_still_gets_a_row():
    """A feed that failed is exactly when the number is worth having — the same rule
    `x_sources` follows for a profile whose signals all died in the prefilter."""
    col = FeedCollector()
    col.warn = lambda msg: None
    def boom(url):
        raise RuntimeError("unreachable")
    col._fetch = boom

    col.collect("AI", {"feeds": {"urls": ["https://dead.dev/f.xml"]}})

    assert [s["url"] for s in col.stats] == ["https://dead.dev/f.xml"]
    assert col.stats[0]["items"] == 0


def test_stats_reset_between_profiles():
    """One collector serves every profile in a run, so the rows must not accumulate."""
    pages = {"https://a.dev/f.xml": _rss(3, "a.dev")}
    col = _collector(pages)
    cfg = {"feeds": {"urls": ["https://a.dev/f.xml"]}}

    col.collect("AI", cfg)
    col.collect("Crypto", cfg)

    assert len(col.stats) == 1, "the second profile inherited the first profile's rows"


def test_the_debug_log_carries_the_feed_rows(tmp_path, monkeypatch):
    """The end of the chain: a count the run log does not write is a count nobody has."""
    import json
    from topicparser import pipeline, store

    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    pages = {"https://a.dev/f.xml": _rss(30, "a.dev")}
    col = _collector(pages)
    monkeypatch.setattr(pipeline.ranker, "rank", lambda *a, **kw: {
        "topics": [], "scored": [], "raw": "", "dropped": {}})

    pipeline.run(selected=["AI"], profiles={"AI": {"feeds": {"urls": list(pages)}}},
                 collectors=[col], client=None, threshold=70, x_days=3, gh_days=60,
                 debug_dir=str(tmp_path))

    log = json.loads(next(tmp_path.glob("run-*.json")).read_text(encoding="utf-8"))
    rows = log["profiles"]["AI"]["feed_sources"]
    assert rows and rows[0]["items"] == 25 and rows[0]["capped"] is True
