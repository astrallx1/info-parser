import topicparser.store as store

def _fresh(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db")
    store.init_db()

def test_ban_repo_adds_to_banned_list(tmp_path):
    _fresh(tmp_path)
    store.ban_repo("owner/foo")
    assert store.list_banned() == [{"repo": "owner/foo",
                                    "url": "https://github.com/owner/foo"}]

def test_ban_repo_removes_from_tracked(tmp_path):
    _fresh(tmp_path)
    store.add_tracked_repo("owner/foo", description="d")
    store.record_stars("owner/foo", 10)
    store.ban_repo("owner/foo")
    assert "owner/foo" not in store.get_tracked_repos()

def test_get_banned_repos_returns_set(tmp_path):
    _fresh(tmp_path)
    store.ban_repo("a/b")
    store.ban_repo("c/d")
    assert store.get_banned_repos() == {"a/b", "c/d"}

def test_ban_repo_is_idempotent(tmp_path):
    _fresh(tmp_path)
    store.ban_repo("a/b")
    store.ban_repo("a/b")
    assert store.get_banned_repos() == {"a/b"}

def test_unban_repo_removes_from_banned(tmp_path):
    _fresh(tmp_path)
    store.ban_repo("a/b")
    store.unban_repo("a/b")
    assert store.get_banned_repos() == set()
    assert store.list_banned() == []
