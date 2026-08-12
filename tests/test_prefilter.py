from datetime import datetime, timezone, timedelta
from topicparser.models import Signal
from topicparser.prefilter import filter_fresh, drop_seen_links, drop_banned

def _sig(url, days_old, source="github", title="t"):
    d = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
    return Signal.make(source=source, title=title, description="d", url=url, date=d, profile="AI")

def test_drop_banned_removes_banned_github_repo():
    sigs = [_sig("u1", 1, title="owner/foo"), _sig("u2", 1, title="owner/bar")]
    kept = drop_banned(sigs, {"owner/foo"})
    assert [s.title for s in kept] == ["owner/bar"]

def test_drop_banned_ignores_x_signals():
    sigs = [_sig("u1", 1, source="x", title="owner/foo")]
    kept = drop_banned(sigs, {"owner/foo"})
    assert [s.url for s in kept] == ["u1"]

def test_drop_banned_empty_set_keeps_all():
    sigs = [_sig("u1", 1, title="owner/foo")]
    assert drop_banned(sigs, set()) == sigs

def test_filter_fresh_drops_old_github():
    sigs = [_sig("u1", 1), _sig("u2", 40)]
    kept = filter_fresh(sigs, gh_days=21, x_days=3)
    assert [s.url for s in kept] == ["u1"]

def test_filter_fresh_x_window_shorter():
    sigs = [_sig("u1", 2, source="x"), _sig("u2", 5, source="x")]
    kept = filter_fresh(sigs, gh_days=21, x_days=3)
    assert [s.url for s in kept] == ["u1"]

def test_filter_fresh_survives_timestamp_without_timezone():
    # a date string carrying no tz offset used to raise
    # "can't subtract offset-naive and offset-aware datetimes" and kill the whole run.
    # Treat a bare timestamp as UTC instead — one odd field must not cost a 15-min scrape.
    fresh = (datetime.now(timezone.utc) - timedelta(days=1)).replace(tzinfo=None).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=40)).replace(tzinfo=None).isoformat()
    sigs = [Signal.make(source="github", title="t", description="d", url="u1",
                        date=fresh, profile="AI"),
            Signal.make(source="github", title="t", description="d", url="u2",
                        date=old, profile="AI")]
    kept = filter_fresh(sigs, gh_days=21, x_days=3)
    assert [s.url for s in kept] == ["u1"]


def test_drop_seen_links():
    sigs = [_sig("u1", 1), _sig("u2", 1)]
    kept = drop_seen_links(sigs, seen={"u1"})
    assert [s.url for s in kept] == ["u2"]
