"""The meta-prompt moved out of the first-run guide and onto the Prompts screen.

It is the text the owner pastes into ChatGPT next to a topic, so it is HIS text, not
pipeline machinery: it must be listed, and it must be editable. The shared files
(`_base`, `_group`, `_xgate`, `_dedup`) stay read-only because they carry the output
contract and a broken one costs a whole run.
"""
import topicparser.prompts_loader as pl


def test_meta_prompt_is_listed():
    rows = pl.list_prompts(["AI"])
    names = [r["name"] for r in rows]
    assert "_meta" in names


def test_meta_prompt_is_editable_but_shared_ones_are_not():
    rows = {r["name"]: r["editable"] for r in pl.list_prompts(["AI"])}
    assert rows["_meta"] is True
    for shared in ("_base", "_group", "_xgate", "_dedup"):
        assert rows[shared] is False


def test_meta_prompt_can_be_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "write_dir", lambda: str(tmp_path))
    errs = pl.save_profile_prompt("_meta", "write the post like this")
    assert errs == []
    assert (tmp_path / "_meta.txt").read_text(encoding="utf-8") == "write the post like this"
