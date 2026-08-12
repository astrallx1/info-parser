"""A saved prompt keeps the previous version, and it can be put back.

The prompt files are the whole product: 33 KB of scoring rules that took months of
replays to tune. Saving used to overwrite the file outright — no backup, no undo, no
version. An empty save is refused, but a three-character one was accepted silently and
the rules were gone for good. One level of backup plus a restore is the smallest thing
that makes the editor safe to open.
"""
import os

from topicparser import i18n
from topicparser import prompts_loader as pl


def _sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(pl.paths, "app_dir", lambda: str(tmp_path))
    return tmp_path / "prompts"


def test_saving_over_an_existing_prompt_keeps_the_previous_version(tmp_path, monkeypatch):
    d = _sandbox(tmp_path, monkeypatch)
    pl.save_profile_prompt("AI", "GATE A -> 45\nGATE C -> 70+")

    pl.save_profile_prompt("AI", "oops")

    assert (d / "AI.txt").read_text(encoding="utf-8") == "oops"
    assert (d / "AI.bak.txt").read_text(encoding="utf-8") == "GATE A -> 45\nGATE C -> 70+"


def test_the_first_save_of_a_new_prompt_has_nothing_to_back_up(tmp_path, monkeypatch):
    d = _sandbox(tmp_path, monkeypatch)

    pl.save_profile_prompt("Fresh", "rules")

    assert not (d / "Fresh.bak.txt").exists()
    assert not pl.has_backup("Fresh")


def test_restore_puts_the_previous_version_back(tmp_path, monkeypatch):
    d = _sandbox(tmp_path, monkeypatch)
    pl.save_profile_prompt("AI", "the real rules")
    pl.save_profile_prompt("AI", "oops")
    assert pl.has_backup("AI")

    assert pl.restore_profile_prompt("AI") == []

    assert (d / "AI.txt").read_text(encoding="utf-8") == "the real rules"


def test_restore_swaps_rather_than_discards(tmp_path, monkeypatch):
    """Restoring is itself undoable — it must not be a one-way door either."""
    d = _sandbox(tmp_path, monkeypatch)
    pl.save_profile_prompt("AI", "version one")
    pl.save_profile_prompt("AI", "version two")

    pl.restore_profile_prompt("AI")

    assert (d / "AI.txt").read_text(encoding="utf-8") == "version one"
    assert (d / "AI.bak.txt").read_text(encoding="utf-8") == "version two"


def test_restore_with_no_backup_reports_it(tmp_path, monkeypatch):
    _sandbox(tmp_path, monkeypatch)
    pl.save_profile_prompt("AI", "only ever this")

    assert pl.restore_profile_prompt("AI") == [i18n.t("err.no_backup")]


def test_a_backup_is_not_listed_as_a_prompt(tmp_path, monkeypatch):
    """`AI.bak.txt` must never show up as a profile named `AI.bak`."""
    _sandbox(tmp_path, monkeypatch)
    pl.save_profile_prompt("AI", "one")
    pl.save_profile_prompt("AI", "two")

    names = [r["name"] for r in pl.list_prompts(["AI"])]

    assert names.count("AI") == 1
    assert not any(".bak" in n for n in names)


def test_the_meta_prompt_is_backed_up_too(tmp_path, monkeypatch):
    d = _sandbox(tmp_path, monkeypatch)
    pl.save_profile_prompt("_meta", "paste this into ChatGPT")

    pl.save_profile_prompt("_meta", "wiped")

    assert (d / "_meta.bak.txt").read_text(encoding="utf-8") == "paste this into ChatGPT"


def test_reading_a_prompt_never_returns_the_backup(tmp_path, monkeypatch):
    _sandbox(tmp_path, monkeypatch)
    pl.save_profile_prompt("AI", "old")
    pl.save_profile_prompt("AI", "new")

    assert pl.read_prompt("AI") == "new"


# --- two asymmetries between the read door and the write door --------------------


def test_reading_a_prompt_cannot_reach_outside_the_prompts_folder(tmp_path, monkeypatch):
    """`save_prompt` validated the name and `get_prompt` did not, so a name is a
    FILENAME on the way in but was trusted on the way out: `../secret` read
    `<app_dir>/../secret.txt`. Guarded in `read_prompt`, which is the one door every
    reader goes through."""
    d = _sandbox(tmp_path, monkeypatch)
    d.mkdir()                                     # the folder beside the app wins
    (tmp_path / "secret.txt").write_text("private", encoding="utf-8")
    assert (d / ".." / "secret.txt").exists()     # the file the old code reached

    assert pl.read_prompt("../secret") == ""
    assert pl.read_prompt("..\\secret") == ""


def test_looking_at_a_prompt_does_not_create_the_prompts_folder(tmp_path, monkeypatch):
    """`has_backup` went through `_backup_path` -> `write_dir`, which makes the folder.
    Opening the Prompts screen therefore created an empty `prompts/` beside the app —
    and beside the app is the REPO when running from source."""
    d = _sandbox(tmp_path, monkeypatch)

    assert pl.has_backup("AI") is False
    assert not d.exists()


def test_saving_still_creates_it(tmp_path, monkeypatch):
    d = _sandbox(tmp_path, monkeypatch)
    pl.save_profile_prompt("AI", "RULES")
    assert d.exists()


def test_an_orphan_backup_is_not_offered_and_cannot_be_restored(tmp_path, monkeypatch):
    """A `.bak.txt` with no `.txt` beside it is not a previous version of anything.

    Found live: `prompts/Crypto.bak.txt` held 11 bytes of test text while the profile's
    real rules came from the PACKAGED copy, which resolution finds per file. `has_backup`
    said yes, so the modal offered «restore» — and the swap would have made those 11
    bytes the live prompt AND written the empty current over the backup, so a second
    press left the profile scoring on `_base` alone. The pair is what makes a swap
    meaningful; a lone backup is refused."""
    d = _sandbox(tmp_path, monkeypatch)
    d.mkdir(parents=True, exist_ok=True)
    (d / "Crypto.bak.txt").write_text("first rules", encoding="utf-8")

    assert not pl.has_backup("Crypto")
    assert pl.restore_profile_prompt("Crypto") == [i18n.t("err.no_backup")]
    assert not (d / "Crypto.txt").exists()
    assert (d / "Crypto.bak.txt").read_text(encoding="utf-8") == "first rules"
