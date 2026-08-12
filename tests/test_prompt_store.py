"""Reading is one thing, WRITING a prompt is another: edits must always land in the
folder beside the app, never in the packaged copy (which is read-only inside a frozen
build and is replaced by the next release anyway)."""
import pytest

from topicparser import prompts_loader as pl


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(pl.paths, "app_dir", lambda: str(tmp_path))
    return tmp_path


def test_write_dir_is_beside_the_app_and_is_created_on_demand(app):
    d = pl.write_dir()
    assert d == str(app / "prompts")
    assert (app / "prompts").is_dir()


def test_saving_a_profile_prompt_writes_beside_the_app_not_into_the_package(app):
    assert pl.save_profile_prompt("Design", "MY RULES") == []
    assert (app / "prompts" / "Design.txt").read_text(encoding="utf-8") == "MY RULES"
    assert "MY RULES" in pl.load_prompt("Design", lang="en")


def test_an_edit_to_a_packaged_profile_shadows_it_without_touching_the_build(
        app, packaged_prompts):
    assert "GATE A" in pl.load_prompt("Shipped", lang="en")     # packaged rules
    pl.save_profile_prompt("Shipped", "REPLACED")
    assert "GATE A" not in pl.load_prompt("Shipped", lang="en")
    assert (app / "prompts" / "Shipped.txt").read_text(encoding="utf-8") == "REPLACED"


def test_an_empty_prompt_is_refused(app):
    # the ranker silently falls back to a 14-line stub when the prompt is empty, and
    # still produces a plausible feed — exactly the failure a bad build once shipped
    errs = pl.save_profile_prompt("Design", "   \n  ")
    assert errs and not (app / "prompts" / "Design.txt").exists()


@pytest.mark.parametrize("name", ["../evil", "_base", "a/b"])
def test_a_dangerous_name_never_reaches_the_filesystem(name, app):
    assert pl.save_profile_prompt(name, "x")
    assert not list((app / "prompts").glob("*")) if (app / "prompts").exists() else True


def test_deleting_a_profile_prompt_removes_only_the_external_copy(app):
    pl.save_profile_prompt("Design", "MY RULES")
    assert pl.delete_profile_prompt("Design") == []
    assert not (app / "prompts" / "Design.txt").exists()


def test_deleting_a_prompt_that_was_never_written_is_not_an_error(app):
    assert pl.delete_profile_prompt("NeverExisted") == []





def test_shared_prompts_are_listed_as_read_only(app):
    kinds = {p["name"]: p for p in pl.list_prompts(["AI", "Crypto"])}
    assert kinds["AI"]["editable"] is True
    assert kinds["_base"]["editable"] is False
    assert kinds["_xgate"]["editable"] is False


def test_reading_a_shared_prompt_returns_the_raw_file(app):
    text = pl.read_prompt("_base")
    assert "CALIBRATION" in text
    assert "{{REASON_LANGUAGE}}" in text     # raw, not assembled — this is the file
