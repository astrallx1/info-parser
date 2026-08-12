"""The Api surface the prompt editor drives.

Two things live here: `_meta` must actually be saveable (it is listed as editable and
the twelve-fix list moved it onto the Prompts screen for that reason), and the editor
needs to know whether a previous version exists so it can offer to put it back.
"""
from topicparser import prompts_loader as pl
from topicparser.api import Api


def _api(tmp_path, monkeypatch, profiles=("AI",)):
    monkeypatch.setattr(pl.paths, "app_dir", lambda: str(tmp_path))
    return Api(profiles={"profiles": {n: {"github": {"topics": []}} for n in profiles}},
               build_collectors=lambda: [], build_client=lambda: None,
               threshold=70, x_days=3, gh_days=60)


def test_the_meta_prompt_can_be_saved(tmp_path, monkeypatch):
    """It is not a profile, so the profile-name check used to reject it outright —
    the screen offered an editor whose Save could never succeed."""
    api = _api(tmp_path, monkeypatch)

    res = api.save_prompt("_meta", "paste this next to the topic")

    assert res == {"ok": True}
    assert pl.read_prompt("_meta") == "paste this next to the topic"


def test_a_shared_prompt_still_cannot_be_saved(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)

    assert "errors" in api.save_prompt("_xgate", "anything")


def test_an_unknown_name_is_still_refused(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)

    assert "errors" in api.save_prompt("NotAProfile", "anything")


def test_get_prompt_reports_whether_a_previous_version_exists(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    api.save_prompt("AI", "first")
    assert api.get_prompt("AI")["has_backup"] is False

    api.save_prompt("AI", "second")

    assert api.get_prompt("AI")["has_backup"] is True


def test_restore_prompt_puts_the_previous_version_back(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    api.save_prompt("AI", "the real rules")
    api.save_prompt("AI", "oops")

    res = api.restore_prompt("AI")

    assert res == {"ok": True, "text": "the real rules"}
    assert pl.read_prompt("AI") == "the real rules"


def test_restore_prompt_with_nothing_to_restore(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    api.save_prompt("AI", "only ever this")

    assert "errors" in api.restore_prompt("AI")


def test_restore_refuses_a_shared_prompt(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)

    assert "errors" in api.restore_prompt("_base")
