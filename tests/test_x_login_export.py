"""`setup_x_login.py` opens the user's REAL Chrome profile, so `storage_state()`
dumps every cookie that profile holds — mail, banking, whatever was logged in — into
`cookies.json`. Only X's are needed. It was also the one credential writer that
skipped `paths.py` and left the file world-readable, while `Api.import_cookies`
chmods it 0600."""
import json
import os
import stat
import sys

import setup_x_login


STATE = {
    "cookies": [
        {"domain": ".x.com", "name": "auth_token", "value": "a"},
        {"domain": "x.com", "name": "ct0", "value": "b"},
        {"domain": ".twitter.com", "name": "auth_token", "value": "c"},
        {"domain": ".linkedin.com", "name": "li_at", "value": "SECRET"},
        {"domain": ".mybank.example", "name": "sessionid", "value": "SECRET"},
        {"domain": ".doubleclick.net", "name": "IDE", "value": "junk"},
        {"domain": "notx.com.evil.example", "name": "spoof", "value": "SECRET"},
    ],
    "origins": [{"origin": "https://mail.example", "localStorage": [{"name": "k",
                                                                    "value": "SECRET"}]}],
}


def test_only_x_cookies_survive():
    out = setup_x_login.x_only(STATE)
    domains = sorted({c["domain"] for c in out["cookies"]})
    assert domains == [".twitter.com", ".x.com", "x.com"]
    assert "SECRET" not in json.dumps(out)


def test_a_lookalike_domain_is_not_x():
    # substring matching would keep "notx.com.evil.example"
    out = setup_x_login.x_only(STATE)
    assert all(not c["domain"].endswith("evil.example") for c in out["cookies"])


def test_other_origins_local_storage_is_dropped():
    out = setup_x_login.x_only(STATE)
    assert out.get("origins") == []


def test_saved_file_is_owner_only(tmp_path):
    path = tmp_path / "cookies.json"
    setup_x_login.write_state(STATE, str(path))
    if not sys.platform.startswith("win"):
        # Windows has no POSIX permission bits: chmod there only toggles the
        # read-only flag and the mode reads back 0o666. The call still runs, it
        # simply cannot express "owner only" — that is the platform, not a bug.
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode == 0o600, oct(mode)
    written = json.loads(path.read_text(encoding="utf-8"))
    assert "SECRET" not in json.dumps(written)
    assert {c["name"] for c in written["cookies"]} == {"auth_token", "ct0"}


def test_the_path_is_anchored_to_the_app_not_the_cwd():
    # a shortcut-launched script inherits an arbitrary CWD; every other runtime
    # path in the app goes through paths.resolve for exactly this reason
    import inspect
    src = inspect.getsource(setup_x_login)
    assert "env_path" in src
    assert 'config.env("COOKIES_PATH"' not in src


# The same hole exists on the OTHER door: a Cookie-Editor "export all" carries every
# site the browser knows, and `Api.import_cookies` wrote whatever it was handed.
def test_convert_keeps_only_x(tmp_path):
    import import_cookies
    raw = [{"name": "auth_token", "value": "a", "domain": ".x.com"},
           {"name": "li_at", "value": "SECRET", "domain": ".linkedin.com"},
           {"name": "spoof", "value": "SECRET", "domain": "notx.com.evil.example"}]
    state = import_cookies.convert(raw)
    assert [c["name"] for c in state["cookies"]] == ["auth_token"]
    assert "SECRET" not in json.dumps(state)


def test_the_two_doors_share_one_filter():
    # one definition of "is this X", or the next fix lands on one door only
    import import_cookies
    assert setup_x_login.x_only is import_cookies.x_only
