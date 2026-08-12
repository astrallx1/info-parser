"""The first-run wall: two API keys and an X session, none of which a non-programmer
can supply by editing a dotfile. The app takes them, checks them, and says plainly
which ones are still missing."""
import json

import pytest

from topicparser import prompts_loader as pl
from topicparser.api import Api


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(pl.paths, "app_dir", lambda: str(tmp_path))
    monkeypatch.setattr("topicparser.paths.app_dir", lambda: str(tmp_path))
    for k in ("GITHUB_TOKEN", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    return Api(profiles={"profiles": {"AI": {"github": {"topics": []}}}},
               build_collectors=lambda: [], build_client=lambda: None,
               threshold=70, x_days=3, gh_days=60)


def test_settings_never_hand_the_ui_a_whole_key(api, tmp_path):
    api.save_settings({"GITHUB_TOKEN": "ghp_abcdefghijklmnop",
                       "OPENAI_API_KEY": "sk-proj-abcdefghijkl"})
    got = api.get_settings()
    assert "abcdefghijklmnop" not in json.dumps(got)
    assert got["GITHUB_TOKEN"].startswith("ghp_") and "…" in got["GITHUB_TOKEN"]
    assert got["has"]["GITHUB_TOKEN"] is True


def test_saving_lands_in_the_env_beside_the_app(api, tmp_path):
    api.save_settings({"GITHUB_TOKEN": "ghp_x"})
    assert "GITHUB_TOKEN=ghp_x" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_an_unknown_setting_is_refused(api):
    # the screen writes .env; it must not become a way to set arbitrary variables
    assert "errors" in api.save_settings({"PATH": "/evil"})


def test_a_blank_value_leaves_the_existing_one_alone(api, tmp_path):
    api.save_settings({"GITHUB_TOKEN": "ghp_keepme"})
    api.save_settings({"GITHUB_TOKEN": "", "LLM_MODEL": "gpt-4.1-mini"})
    assert "ghp_keepme" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_setup_state_names_what_is_still_missing(api, tmp_path):
    st = api.setup_state()
    assert st["needs_onboarding"] is True
    assert set(st["missing"]) == {"GITHUB_TOKEN", "OPENAI_API_KEY", "cookies"}

    api.save_settings({"GITHUB_TOKEN": "g", "OPENAI_API_KEY": "o"})
    (tmp_path / "cookies.json").write_text(
        json.dumps({"cookies": [{"name": "auth_token"}, {"name": "ct0"}]}), encoding="utf-8")
    st = api.setup_state()
    assert st["needs_onboarding"] is False and st["missing"] == []


def test_x_is_optional_so_only_the_keys_block_onboarding(api, tmp_path):
    api.save_settings({"GITHUB_TOKEN": "g", "OPENAI_API_KEY": "o"})
    st = api.setup_state()
    assert st["missing"] == ["cookies"]
    assert st["needs_onboarding"] is False       # GitHub-only runs are a valid setup


def test_importing_cookies_accepts_a_cookie_editor_export(api, tmp_path):
    export = json.dumps([
        {"name": "auth_token", "value": "a", "domain": ".x.com", "expirationDate": 1e10},
        {"name": "ct0", "value": "b", "domain": ".x.com", "session": True},
    ])
    res = api.import_cookies(export)
    assert res["ok"] and res["count"] == 2
    state = json.loads((tmp_path / "cookies.json").read_text(encoding="utf-8"))
    assert {c["name"] for c in state["cookies"]} == {"auth_token", "ct0"}
    assert state["origins"] == []


def test_an_export_without_the_session_cookies_is_reported_not_silently_saved(api, tmp_path):
    res = api.import_cookies(json.dumps([{"name": "guest_id", "value": "x"}]))
    assert "errors" in res
    assert not (tmp_path / "cookies.json").exists()


def test_garbage_pasted_into_the_cookie_box_is_an_error_not_a_crash(api):
    assert "errors" in api.import_cookies("not json at all")
    assert "errors" in api.import_cookies("")


def test_the_meta_prompt_is_available_and_mentions_the_format(api):
    # the guide's Copy button reads it through get_prompt, like every other file
    text = api.get_prompt("_meta")["text"]
    assert len(text) > 400
    assert "0-100" in text          # it has to teach the scoring contract


def test_the_meta_prompt_carries_no_keys_or_sources(api, tmp_path):
    api.save_settings({"GITHUB_TOKEN": "ghp_secret_value"})
    assert "ghp_secret_value" not in api.get_prompt("_meta")["text"]


class _Resp:
    def __init__(self, code, payload=None):
        self.status_code, self._p = code, payload or {}

    def json(self):
        return self._p


def test_verifying_github_reports_the_account_it_belongs_to(api, monkeypatch):
    api.save_settings({"GITHUB_TOKEN": "ghp_x"})
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(200, {"login": "astrallx1"}))
    assert api.verify_key("GITHUB_TOKEN") == {"ok": True, "detail": "astrallx1"}


def test_a_rejected_github_token_says_so(api, monkeypatch):
    api.save_settings({"GITHUB_TOKEN": "ghp_bad"})
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(401))
    assert "errors" in api.verify_key("GITHUB_TOKEN")


def test_verifying_with_no_key_at_all_is_an_error_not_a_call(api, monkeypatch):
    called = []
    monkeypatch.setattr("requests.get", lambda *a, **k: called.append(1) or _Resp(200))
    assert "errors" in api.verify_key("GITHUB_TOKEN")
    assert called == []


def test_a_dead_network_is_reported_rather_than_raised(api, monkeypatch):
    api.save_settings({"GITHUB_TOKEN": "ghp_x"})

    def boom(*a, **k):
        raise OSError("no route to host")

    monkeypatch.setattr("requests.get", boom)
    assert "errors" in api.verify_key("GITHUB_TOKEN")


def test_verifying_openai_names_the_model_it_reached(api, monkeypatch):
    api.save_settings({"OPENAI_API_KEY": "sk-x", "LLM_MODEL": "gpt-4.1-mini"})
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(
        200, {"data": [{"id": "gpt-4.1-mini"}, {"id": "gpt-5"}]}))
    assert api.verify_key("OPENAI_API_KEY")["ok"] is True


def test_an_unknown_key_name_cannot_be_probed(api):
    assert "errors" in api.verify_key("PATH")
