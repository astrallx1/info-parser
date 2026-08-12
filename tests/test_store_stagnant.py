import topicparser.store as store


def _fresh(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db")
    store.init_db()


def test_drop_stagnant_removes_repo_not_grown_in_window(tmp_path):
    _fresh(tmp_path)
    store.add_tracked_repo("stale/repo")
    store._set_last_growing("stale/repo", days_ago=30)   # stagnant 30 days

    removed = store.drop_stagnant_repos(days=21)

    assert removed == ["stale/repo"]
    assert "stale/repo" not in store.get_tracked_repos()
    assert store.velocity("stale/repo") is None          # history cleared too


def test_drop_stagnant_keeps_freshly_added_repo(tmp_path):
    _fresh(tmp_path)
    store.add_tracked_repo("fresh/repo")                  # last_growing = now

    removed = store.drop_stagnant_repos(days=21)

    assert removed == []
    assert "fresh/repo" in store.get_tracked_repos()


def test_star_growth_resets_stagnation(tmp_path):
    _fresh(tmp_path)
    store.add_tracked_repo("grow/repo")
    store._set_last_growing("grow/repo", days_ago=30)     # looks stagnant
    store.record_stars("grow/repo", 5)                    # first snapshot (no prior)
    store.record_stars("grow/repo", 50)                   # grew -> should reset last_growing

    removed = store.drop_stagnant_repos(days=21)

    assert removed == []                                  # growth kept it alive
    assert "grow/repo" in store.get_tracked_repos()


def test_flat_stars_do_not_reset_stagnation(tmp_path):
    _fresh(tmp_path)
    store.add_tracked_repo("flat/repo")
    store._set_last_growing("flat/repo", days_ago=30)
    store.record_stars("flat/repo", 40)
    store.record_stars("flat/repo", 40)                   # no growth -> no reset

    removed = store.drop_stagnant_repos(days=21)

    assert removed == ["flat/repo"]
