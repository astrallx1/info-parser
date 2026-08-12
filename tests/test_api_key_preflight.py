"""A run must not start on a key that does not work.

`setup_state` only asks whether a key is NON-EMPTY. That is how placeholder text
("sasdas…") sat in `.env` for a day: the app considered itself configured, the guide
did not open, the pre-run check passed, and the run would have spent a 15-minute
scrape before dying on the first scoring call. Presence is not validity.
"""
import pytest

from topicparser import i18n
from topicparser.api import Api


def make(**kw):
    return Api(profiles={"profiles": {}}, build_collectors=lambda: [],
               build_client=lambda: None, threshold=70, x_days=3, gh_days=60, **kw)


def test_both_keys_working_reports_ok(monkeypatch):
    api = make()
    monkeypatch.setattr(api, "verify_key", lambda name: {"ok": True, "detail": "x"})
    assert api.check_keys() == {"ok": True, "rejected": []}


def test_a_rejected_key_is_named(monkeypatch):
    api = make()
    monkeypatch.setattr(api, "verify_key",
                        lambda name: {"ok": True} if name == "GITHUB_TOKEN"
                        else {"errors": ["rejected (401)"]})
    out = api.check_keys()
    assert out["ok"] is False
    assert out["rejected"] == ["OPENAI_API_KEY"]


def test_both_rejected_are_both_named(monkeypatch):
    api = make()
    monkeypatch.setattr(api, "verify_key", lambda name: {"errors": ["rejected (401)"]})
    assert api.check_keys()["rejected"] == ["GITHUB_TOKEN", "OPENAI_API_KEY"]


def test_the_check_never_raises(monkeypatch):
    """A dead network must not stop a run the user asked for — it degrades to
    'cannot tell', not to 'refuse'."""
    def boom(name):
        raise RuntimeError("no route to host")

    api = make()
    monkeypatch.setattr(api, "verify_key", boom)
    assert api.check_keys() == {"ok": True, "rejected": []}


@pytest.mark.parametrize("key", ["GITHUB_TOKEN", "OPENAI_API_KEY"])
def test_the_catalogue_can_name_the_rejected_key(key):
    label = i18n.t("settings.github" if key == "GITHUB_TOKEN" else "settings.openai")
    assert label and not label.startswith("settings.")
    msg = i18n.t("status.keys_rejected", keys=label)
    assert msg != "status.keys_rejected" and label in msg


def test_the_ui_checks_validity_before_it_starts_a_run():
    """The guard belongs where the human presses the button. `run_parser` itself is
    left alone on purpose: it is called once per run by the UI, and putting two
    network calls inside the pipeline path would make every test that exercises a run
    reach out."""
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ui = open(os.path.join(root, "topicparser", "ui", "index.html"), encoding="utf-8").read()
    block = ui[ui.index("async function runParser"):ui.index("async function stopRun")]
    assert "check_keys()" in block
    assert "status.keys_rejected" in block
    # and it must happen BEFORE the run is dispatched
    assert block.index("check_keys()") < block.index("run_parser(selection)")


# --- the check must not confuse "unreachable" with "rejected" -------------------
#
# `check_keys` reads `verify_key`'s answer, and `verify_key` reported a dead network
# exactly the way it reports a 401. So a proxy, a DNS blip or GitHub having a bad
# hour named both keys as rejected, the UI refused to start the run, and the message
# told the user their keys were bad. The docstring promised the opposite.

class _Resp:
    def __init__(self, code, payload=None):
        self.status_code, self._p = code, payload or {}

    def json(self):
        return self._p


@pytest.fixture
def keyed(tmp_path, monkeypatch):
    monkeypatch.setattr("topicparser.paths.app_dir", lambda: str(tmp_path))
    api = make()
    api.save_settings({"GITHUB_TOKEN": "ghp_x", "OPENAI_API_KEY": "sk-x"})
    return api


def test_a_dead_network_does_not_read_as_a_rejected_key(keyed, monkeypatch):
    def boom(*a, **k):
        raise OSError("no route to host")

    monkeypatch.setattr("requests.get", boom)
    assert keyed.check_keys() == {"ok": True, "rejected": []}


def test_the_probe_being_down_does_not_read_as_a_rejected_key(keyed, monkeypatch):
    """503 from GitHub says nothing about the token. Neither does 429."""
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(503))
    assert keyed.check_keys() == {"ok": True, "rejected": []}


def test_a_real_401_still_stops_the_run(keyed, monkeypatch):
    """The only status that judges the key. Both probes answer a bad key with it."""
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(401))
    assert keyed.check_keys()["rejected"] == ["GITHUB_TOKEN", "OPENAI_API_KEY"]


def test_a_403_is_not_a_verdict_about_the_key(keyed, monkeypatch):
    """GitHub returns 403 for a secondary rate limit, an SSO-unauthorised token and an
    IP allowlist; OpenAI for an unsupported region. None of those is a bad key, and a
    valid key on a bad day must not stop the run."""
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(403))
    assert keyed.check_keys() == {"ok": True, "rejected": []}


def test_a_missing_key_still_stops_the_run(tmp_path, monkeypatch):
    """Nothing to verify is not doubt: it is the state the guide exists to fix."""
    monkeypatch.setattr("topicparser.paths.app_dir", lambda: str(tmp_path))
    # the keys are read from the environment as well as the file now, and the
    # developer running this has both set
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    api = make()
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(200))
    assert api.check_keys()["rejected"] == ["GITHUB_TOKEN", "OPENAI_API_KEY"]


def test_the_user_still_sees_why_a_verify_failed(keyed, monkeypatch):
    """Unreachable is not silent — the Verify button must still report it."""
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(503))
    out = keyed.verify_key("GITHUB_TOKEN")
    assert out.get("errors") and not out.get("ok")
