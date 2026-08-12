import topicparser.store as store
from topicparser.api import Api


def _api():
    return Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
               threshold=80, x_days=3, gh_days=21)


def test_ban_repo_by_url_normalizes_to_owner_repo(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    _api().ban_repo("https://github.com/owner/foo")
    assert store.get_banned_repos() == {"owner/foo"}


def test_ban_repo_by_owner_repo(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    _api().ban_repo("owner/foo")
    assert store.get_banned_repos() == {"owner/foo"}


def test_ban_repo_removes_from_watchlist(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    store.add_tracked_repo("owner/foo", description="d")
    _api().ban_repo("owner/foo")
    assert "owner/foo" not in store.get_tracked_repos()


def test_list_banned(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    _api().ban_repo("owner/foo")
    assert _api().list_banned() == [{"repo": "owner/foo",
                                     "url": "https://github.com/owner/foo"}]


def test_ban_repo_drops_its_topic_from_the_md(tmp_path):
    """Banning hides the card, but the .md reads `kept` — so a ban that leaves
    `kept` alone still exports the repo the user just threw out."""
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    banned = store.insert_topic(title="owner/foo", why="w", score=80, profile="AI",
                                run_id="r1",
                                links=["https://github.com/owner/foo"], signature="owner/foo")
    keeper = store.insert_topic(title="owner/bar", why="w", score=80, profile="AI",
                                run_id="r1",
                                links=["https://github.com/owner/bar"], signature="owner/bar")
    api = _api()
    api._last_topic_ids = {banned, keeper}
    api.ban_repo("https://github.com/owner/foo")
    out = tmp_path / "run.md"
    api.save_md(str(out))
    text = out.read_text(encoding="utf-8")
    assert "owner/bar" in text
    assert "owner/foo" not in text


def test_ban_repo_spares_a_repo_sharing_its_prefix(tmp_path):
    """`owner/foo` must not drag `owner/foobar` out of the .md with it."""
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    neighbour = store.insert_topic(title="owner/foobar", why="w", score=80, profile="AI",
                                   run_id="r1",
                                   links=["https://github.com/owner/foobar"],
                                   signature="owner/foobar")
    api = _api()
    api._last_topic_ids = {neighbour}
    api.ban_repo("owner/foo")
    out = tmp_path / "run.md"
    api.save_md(str(out))
    assert "owner/foobar" in out.read_text(encoding="utf-8")


def test_unban_repo(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    _api().ban_repo("owner/foo")
    _api().unban_repo("owner/foo")
    assert store.get_banned_repos() == set()
