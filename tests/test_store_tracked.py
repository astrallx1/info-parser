from datetime import datetime, timezone, timedelta
import topicparser.store as store


def _fresh(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db")
    store.init_db()


def test_remove_tracked_repo_deletes_repo_and_history(tmp_path):
    _fresh(tmp_path)
    store.add_tracked_repo("owner/repo")
    store.record_stars("owner/repo", 100)
    assert "owner/repo" in store.get_tracked_repos()

    store.remove_tracked_repo("owner/repo")

    assert "owner/repo" not in store.get_tracked_repos()
    assert store.velocity("owner/repo") is None       # history gone too
    assert store.get_tracked_detail() == []


def test_get_tracked_detail_reports_stars_added_and_velocity(tmp_path):
    _fresh(tmp_path)
    store.add_tracked_repo("owner/repo")
    now = datetime.now(timezone.utc)
    store.record_stars("owner/repo", 100, at=(now - timedelta(days=2)).isoformat())
    store.record_stars("owner/repo", 300, at=now.isoformat())

    rows = store.get_tracked_detail()

    assert len(rows) == 1
    r = rows[0]
    assert r["repo"] == "owner/repo"
    assert r["stars"] == 300           # latest measurement
    assert r["velocity"] == 100.0      # (300-100)/2 days
    assert r["added"]                  # non-empty ISO timestamp


def test_get_tracked_detail_reports_last_measured_timestamp(tmp_path):
    _fresh(tmp_path)
    store.add_tracked_repo("owner/repo")
    now = datetime.now(timezone.utc)
    store.record_stars("owner/repo", 100, at=(now - timedelta(days=2)).isoformat())
    store.record_stars("owner/repo", 300, at=now.isoformat())

    r = store.get_tracked_detail()[0]

    assert r["last_measured"] == now.isoformat()   # latest snapshot's timestamp


def test_get_tracked_detail_last_measured_none_without_measurements(tmp_path):
    _fresh(tmp_path)
    store.add_tracked_repo("new/repo")
    assert store.get_tracked_detail()[0]["last_measured"] is None


def test_get_tracked_detail_velocity_none_with_one_measurement(tmp_path):
    _fresh(tmp_path)
    store.add_tracked_repo("solo/repo")
    store.record_stars("solo/repo", 50)

    rows = store.get_tracked_detail()

    assert len(rows) == 1
    assert rows[0]["stars"] == 50
    assert rows[0]["velocity"] is None


def test_get_tracked_detail_stars_none_without_measurements(tmp_path):
    _fresh(tmp_path)
    store.add_tracked_repo("new/repo")

    rows = store.get_tracked_detail()

    assert len(rows) == 1
    assert rows[0]["repo"] == "new/repo"
    assert rows[0]["stars"] is None
    assert rows[0]["velocity"] is None


def test_tracked_detail_has_description_and_url(tmp_path):
    _fresh(tmp_path)
    store.add_tracked_repo("owner/repo", description="a cool AI tool")
    r = store.get_tracked_detail()[0]
    assert r["description"] == "a cool AI tool"
    assert r["url"] == "https://github.com/owner/repo"


def test_re_adding_backfills_description(tmp_path):
    _fresh(tmp_path)
    store.add_tracked_repo("owner/repo")                      # no description yet
    store.add_tracked_repo("owner/repo", description="filled later")
    assert store.get_tracked_detail()[0]["description"] == "filled later"
