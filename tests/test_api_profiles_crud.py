"""Profiles used to be a fixed set: adding one meant a yaml entry AND a prompt file,
i.e. a code change. For anyone but the owner that is the wall — so the UI can now
create, rename and delete them, and the prompt file follows along."""
import pytest
import yaml

from topicparser import prompts_loader as pl
from topicparser.api import Api

BASE = {"profiles": {"AI": {"github": {"topics": ["mcp"]},
                            "x": {"accounts": [], "lists": [], "searches": []}}}}


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(pl.paths, "app_dir", lambda: str(tmp_path))
    path = tmp_path / "profiles.yaml"
    path.write_text(yaml.safe_dump(BASE, allow_unicode=True), encoding="utf-8")
    a = Api(profiles=yaml.safe_load(path.read_text(encoding="utf-8")),
            build_collectors=lambda: [], build_client=lambda: None,
            threshold=70, x_days=3, gh_days=60, profiles_path=str(path))
    a._dir = tmp_path
    return a


def _yaml(api):
    return yaml.safe_load(open(api._profiles_path, encoding="utf-8").read())["profiles"]


def test_adding_a_profile_persists_it_and_gives_it_a_starter_prompt(api):
    assert api.add_profile("Design") == {"ok": True}
    assert "Design" in _yaml(api)
    text = pl.read_prompt("Design")
    assert text.strip()                       # never an empty file
    assert "SCORE" in text.upper()            # the skeleton, not a blank page


def test_a_new_profile_has_empty_sources_but_a_valid_shape(api):
    api.add_profile("Design")
    cfg = _yaml(api)["Design"]
    assert cfg["github"]["topics"] == []
    assert cfg["x"] == {"accounts": [], "lists": [], "searches": []}


def test_a_duplicate_name_is_refused(api):
    assert "errors" in api.add_profile("AI")


@pytest.mark.parametrize("name", ["../evil", "_base", "a/b", "  "])
def test_a_dangerous_name_is_refused_before_anything_is_written(name, api):
    assert "errors" in api.add_profile(name)
    assert list(_yaml(api)) == ["AI"]


def test_renaming_moves_both_the_config_and_the_prompt(api):
    api.add_profile("Design")
    pl.save_profile_prompt("Design", "MY OWN RULES")
    assert api.rename_profile("Design", "Product") == {"ok": True}
    assert "Design" not in _yaml(api) and "Product" in _yaml(api)
    assert pl.read_prompt("Product") == "MY OWN RULES"


def test_renaming_keeps_the_sources(api):
    api.add_profile("Design")
    api.save_profiles({"profiles": {**_yaml(api),
                                    "Design": {"github": {"topics": ["figma"]},
                                               # stored WITHOUT the @ — normalize() strips
                                               # it, and validation now refuses it
                                               "x": {"accounts": ["figma"], "lists": [], "searches": []}}}})
    api.rename_profile("Design", "Product")
    assert _yaml(api)["Product"]["github"]["topics"] == ["figma"]


def test_renaming_onto_an_existing_profile_is_refused(api):
    api.add_profile("Design")
    assert "errors" in api.rename_profile("Design", "AI")
    assert "Design" in _yaml(api)


def test_renaming_something_that_does_not_exist_is_refused(api):
    assert "errors" in api.rename_profile("Ghost", "Product")


def test_deleting_removes_the_profile_and_its_prompt(api):
    api.add_profile("Design")
    assert api.delete_profile("Design") == {"ok": True}
    assert "Design" not in _yaml(api)
    assert pl.read_prompt("Design") == ""


def test_the_last_profile_cannot_be_deleted(api):
    # `validate_profiles` treats an empty set as invalid, and an app with no profile
    # can do nothing at all — refuse rather than write a config that fails to load
    assert "errors" in api.delete_profile("AI")
    assert "AI" in _yaml(api)


def test_the_running_api_sees_the_change_without_a_restart(api):
    api.add_profile("Design")
    assert "Design" in api.get_profiles()["profiles"]
    api.delete_profile("Design")
    assert "Design" not in api.get_profiles()["profiles"]


# --- rename: the profile must never be left without its rules ----------------------


def test_a_failed_yaml_write_does_not_leave_the_old_profile_promptless(api, monkeypatch):
    """The prompt move ran BEFORE the yaml write, so a failing write left `Old.txt`
    deleted while the config still said `Old` — and a profile with no prompt scores on
    the ranker's 14-line stub and produces a plausible-looking feed with every rule
    gone. Copy first, write, then delete: any failure leaves an ORPHAN prompt, which
    costs nothing."""
    pl.save_profile_prompt("AI", "OLD RULES")
    monkeypatch.setattr(api, "_write_profiles",
                        lambda p: {"errors": ["disk full"]})

    out = api.rename_profile("AI", "New")

    assert out.get("errors")
    assert pl.read_prompt("AI") == "OLD RULES", "the live profile lost its rules"
