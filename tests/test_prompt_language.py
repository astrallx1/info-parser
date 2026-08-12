"""`_base.txt` holds machinery and shared taste; every sentence that names a language
lives in `_language.<code>.txt`. These tests are language-agnostic on purpose — the
proof that the split left the OWNER's prompt untouched is a separate migration test
that ships with his private repo only."""
import pytest

from topicparser import prompts_loader


def test_english_assembly_carries_no_ukrainian_rule():
    en = prompts_loader.load_base(lang="en")
    assert "UKRAINIAN" not in en.upper()
    assert not any("Ѐ" <= c <= "ӿ" for c in en)   # no Cyrillic at all
    # the machinery is untouched — same contract, same calibration
    assert '{"scored":[{"i":<index>' in en
    assert "CALIBRATION" in en


def test_the_machinery_survives_a_language_swap(tmp_path, monkeypatch):
    ext = tmp_path / "prompts"; ext.mkdir()
    (ext / "_language.zz.txt").write_text(
        "[[reason]]\nREASON RULE ZZ\n[[title]]\nTITLE RULE ZZ\n", encoding="utf-8")
    monkeypatch.setattr(prompts_loader.paths, "app_dir", lambda: str(tmp_path))
    zz = prompts_loader.load_base(lang="zz")
    assert "REASON RULE ZZ" in zz and "TITLE RULE ZZ" in zz
    assert "{{REASON_LANGUAGE}}" not in zz and "{{TITLE_LANGUAGE}}" not in zz
    for line in ["SCORE HIGH (70-100)", "OFF-INTEREST HARD CAP", "CALIBRATION",
                 "OUTPUT — return STRICT JSON, nothing else:"]:
        assert line in zz


def test_unknown_language_falls_back_to_english():
    assert prompts_loader.load_base(lang="xx") == prompts_loader.load_base(lang="en")


def test_load_prompt_appends_the_profile_on_top_of_the_assembled_base(packaged_prompts):
    p = prompts_loader.load_prompt("Shipped", lang="en")
    assert p.startswith(prompts_loader.load_base(lang="en"))
    assert "GATE A" in p


def test_external_prompts_dir_overrides_per_file_not_wholesale(tmp_path, monkeypatch,
                                                               packaged_prompts):
    # The owner keeps ONE file outside the package (_language.uk.txt). All-or-nothing
    # resolution would hide every other packaged prompt and silently gut scoring.
    ext = tmp_path / "prompts"
    ext.mkdir()
    (ext / "_group.txt").write_text("MY OWN GROUPING", encoding="utf-8")
    monkeypatch.setattr(prompts_loader.paths, "app_dir", lambda: str(tmp_path))

    assert prompts_loader.load_group_prompt() == "MY OWN GROUPING"       # overridden
    assert "GATE A" in prompts_loader.load_prompt("Shipped", lang="en")  # still packaged
