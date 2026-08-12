from datetime import datetime, timezone, timedelta
import topicparser.store as store


def _fresh(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db")
    store.init_db()


def _iso(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _hours_ago(h):
    return (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()


def test_no_alert_when_interval_too_short(tmp_path):
    # two runs close in time (e.g. 3h) inflate stars/day by extrapolation:
    # +400 over 3h -> 3200/day. That is noise, not a real daily rate -> no alert.
    _fresh(tmp_path)
    store.add_tracked_repo("hot/repo")
    store.record_stars("hot/repo", 100, at=_hours_ago(3))
    store.record_stars("hot/repo", 500, at=_hours_ago(0))

    assert store.detect_trending(min_velocity=50) == []       # guarded by min_hours (default 12)


def test_alerts_when_interval_long_enough(tmp_path):
    # same idea but measured over a real window -> a trustworthy /day rate -> alert
    _fresh(tmp_path)
    store.add_tracked_repo("hot/repo")
    store.record_stars("hot/repo", 100, at=_hours_ago(24))
    store.record_stars("hot/repo", 200, at=_hours_ago(0))     # +100 / 1d = 100/day, 24h >= 12h

    assert [a["repo"] for a in store.detect_trending(min_velocity=50)] == ["hot/repo"]


def test_alerts_on_first_velocity_spike(tmp_path):
    _fresh(tmp_path)
    store.add_tracked_repo("hot/repo", description="a breakout tool")
    store.record_stars("hot/repo", 100, at=_iso(2))
    store.record_stars("hot/repo", 500, at=_iso(0))      # +400 / 2d = 200 stars/day

    alerts = store.detect_trending(min_velocity=50)

    assert [a["repo"] for a in alerts] == ["hot/repo"]
    assert abs(alerts[0]["velocity"] - 200.0) < 1
    assert alerts[0]["stars"] == 500
    assert alerts[0]["url"] == "https://github.com/hot/repo"
    assert alerts[0]["description"] == "a breakout tool"


def test_no_alert_below_threshold(tmp_path):
    _fresh(tmp_path)
    store.add_tracked_repo("slow/repo")
    store.record_stars("slow/repo", 100, at=_iso(2))
    store.record_stars("slow/repo", 110, at=_iso(0))     # 5 stars/day

    assert store.detect_trending(min_velocity=50) == []


def test_no_repeat_alert_while_still_hot(tmp_path):
    _fresh(tmp_path)
    store.add_tracked_repo("hot/repo")
    store.record_stars("hot/repo", 100, at=_iso(4))
    store.record_stars("hot/repo", 500, at=_iso(2))      # prev pair: 200/day (hot)
    store.record_stars("hot/repo", 1000, at=_iso(0))     # cur pair: 250/day (still hot)

    assert store.detect_trending(min_velocity=50) == []  # already hot last run -> silent


def test_realerts_after_cooldown(tmp_path):
    _fresh(tmp_path)
    store.add_tracked_repo("hot/repo")
    store.record_stars("hot/repo", 100, at=_iso(6))
    store.record_stars("hot/repo", 110, at=_iso(4))      # prev pair: 5/day (cold)
    store.record_stars("hot/repo", 600, at=_iso(0))      # cur pair: ~122/day (hot again)

    alerts = store.detect_trending(min_velocity=50)
    assert [a["repo"] for a in alerts] == ["hot/repo"]


def test_no_alert_with_single_measurement(tmp_path):
    _fresh(tmp_path)
    store.add_tracked_repo("new/repo")
    store.record_stars("new/repo", 100, at=_iso(0))      # only one snapshot -> no velocity

    assert store.detect_trending(min_velocity=50) == []


# --- the 12h guard must skip a short interval, not give up on the repo -----------
#
# `velocity` looked at the two NEWEST snapshots and `detect_trending` at the newest
# three. The min_hours floor is right (a 2h gain extrapolates to an absurd /day rate)
# but it was applied to that one pair and then answered None — so a second run the
# same day permanently hid a breakout that older snapshots measure perfectly well.
# Anyone running the parser twice a day never saw a single alert.


def test_an_extra_run_does_not_hide_a_breakout(tmp_path):
    _fresh(tmp_path)
    store.add_tracked_repo("hot/repo")
    store.record_stars("hot/repo", 100, at=_hours_ago(48))
    store.record_stars("hot/repo", 500, at=_hours_ago(2))    # breakout: ~208/day
    store.record_stars("hot/repo", 510, at=_hours_ago(0))    # one more run, 2h later

    alerts = store.detect_trending(min_velocity=50)

    assert [a["repo"] for a in alerts] == ["hot/repo"]
    assert abs(alerts[0]["velocity"] - 205) < 5              # measured 0h against 48h


def test_a_breakout_that_already_rang_stays_silent_with_an_extra_run(tmp_path):
    """The repo was already hot last run, so this must stay silent even though the
    two newest snapshots are an hour apart."""
    _fresh(tmp_path)
    store.add_tracked_repo("hot/repo")
    store.record_stars("hot/repo", 100, at=_hours_ago(100))
    store.record_stars("hot/repo", 900, at=_hours_ago(12))   # prev window: ~218/day, hot
    store.record_stars("hot/repo", 1400, at=_hours_ago(1))
    store.record_stars("hot/repo", 1410, at=_hours_ago(0))   # cur window: 0h vs 12h, hot

    assert store.detect_trending(min_velocity=50) == []


def test_the_table_and_the_alert_measure_the_same_interval(tmp_path):
    """The tracked table renders `velocity()` while the alert carries its own number.
    They read the same history and must not disagree: the table showing 'measuring'
    while the alert announces a breakout is the state this pair was in."""
    _fresh(tmp_path)
    store.add_tracked_repo("hot/repo")
    store.record_stars("hot/repo", 100, at=_hours_ago(48))
    store.record_stars("hot/repo", 500, at=_hours_ago(2))
    store.record_stars("hot/repo", 510, at=_hours_ago(0))

    alerts = store.detect_trending(min_velocity=50)
    assert alerts and store.velocity("hot/repo") == alerts[0]["velocity"]


def test_the_previous_velocity_is_measured_from_where_the_current_one_ends(tmp_path):
    """A cold repo breaking out NOW must alert, and `prev` decides that.

    Anchored on the next ROW instead of on the end of `cur`'s window, `prev` measures
    an interval that OVERLAPS the breakout — 1h against 24h below, which is 824/day —
    reads as "it was already hot", and swallows the alert. Measured from where `cur`
    ends it sees the cold week that actually preceded it."""
    _fresh(tmp_path)
    store.add_tracked_repo("hot/repo")
    store.record_stars("hot/repo", 100, at=_hours_ago(100))
    store.record_stars("hot/repo", 110, at=_hours_ago(24))    # prev window: ~3/day, cold
    store.record_stars("hot/repo", 900, at=_hours_ago(1))     # the breakout
    store.record_stars("hot/repo", 910, at=_hours_ago(0))     # cur window: 0h vs 24h

    assert [a["repo"] for a in store.detect_trending(min_velocity=50)] == ["hot/repo"]
