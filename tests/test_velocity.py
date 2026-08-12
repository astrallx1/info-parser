import topicparser.store as store

def _fresh(tmp_path): store.DB_PATH = str(tmp_path/"t.db"); store.init_db()

def test_velocity_normalizes_by_days(tmp_path):
    _fresh(tmp_path)
    store.add_tracked_repo("foo/bar")
    store.record_stars("foo/bar", 1000, at="2026-07-01T00:00:00+00:00")
    store.record_stars("foo/bar", 1150, at="2026-07-03T00:00:00+00:00")
    assert round(store.velocity("foo/bar"), 1) == 75.0     # 150 / 2 days

def test_velocity_none_with_one_measure(tmp_path):
    _fresh(tmp_path)
    store.add_tracked_repo("foo/bar")
    store.record_stars("foo/bar", 1000, at="2026-07-01T00:00:00+00:00")
    assert store.velocity("foo/bar") is None

def test_velocity_none_when_interval_under_min_hours(tmp_path):
    # two runs ~1h apart must NOT extrapolate a real 1h gain into a per-day rate
    _fresh(tmp_path)
    store.add_tracked_repo("foo/bar")
    store.record_stars("foo/bar", 1000, at="2026-07-01T00:00:00+00:00")
    store.record_stars("foo/bar", 1084, at="2026-07-01T01:00:00+00:00")
    assert store.velocity("foo/bar") is None     # 1h < min_hours=12 -> guarded
