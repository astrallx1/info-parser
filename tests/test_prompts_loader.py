from topicparser.prompts_loader import load_prompt

def _write(d, name, text):
    p = d / name
    p.write_text(text, encoding="utf-8")

def test_combines_base_and_profile(tmp_path):
    _write(tmp_path, "_base.txt", "BASE RULES")
    _write(tmp_path, "AI.txt", "AI FOCUS")
    out = load_prompt("AI", prompts_dir=str(tmp_path))
    assert "BASE RULES" in out and "AI FOCUS" in out
    assert out.index("BASE RULES") < out.index("AI FOCUS")   # base first

def test_missing_profile_falls_back_to_base(tmp_path):
    _write(tmp_path, "_base.txt", "BASE RULES")
    out = load_prompt("Nope", prompts_dir=str(tmp_path))
    assert out == "BASE RULES"


def test_load_group_prompt_reads_group_file(tmp_path):
    from topicparser.prompts_loader import load_group_prompt
    _write(tmp_path, "_group.txt", "GROUP RULES")
    assert load_group_prompt(prompts_dir=str(tmp_path)) == "GROUP RULES"


def test_load_group_prompt_missing_file_is_empty(tmp_path):
    from topicparser.prompts_loader import load_group_prompt
    assert load_group_prompt(prompts_dir=str(tmp_path)) == ""


def test_default_dir_prefers_prompts_beside_the_app_over_the_packaged_copy(
        monkeypatch, tmp_path, packaged_prompts):
    # The whole point of shipping the prompts OUTSIDE the bundle: the owner tunes
    # scoring by editing a .txt beside the .exe, with no repackaging. An external
    # `prompts/` folder therefore wins — but PER FILE (2026-08-07): dropping one file
    # there used to hide every other packaged prompt, which would silently gut scoring
    # for anyone keeping just a language fragment outside the build.
    from topicparser import paths, prompts_loader
    external = tmp_path / "prompts"
    external.mkdir()
    (external / "_base.txt").write_text("EXTERNAL RULES", encoding="utf-8")
    monkeypatch.setattr(paths, "app_dir", lambda: str(tmp_path))
    assert prompts_loader.prompts_dir() == str(external)
    prompt = load_prompt("Shipped")
    assert prompt.startswith("EXTERNAL RULES")   # the overridden file wins
    assert "GATE A" in prompt                    # the rest still comes from the build


def test_default_dir_falls_back_to_the_packaged_prompts(monkeypatch, tmp_path,
                                                        packaged_prompts):
    # nothing beside the app -> the shipped rules, i.e. exactly today's behaviour
    from topicparser import paths
    monkeypatch.setattr(paths, "app_dir", lambda: str(tmp_path))
    assert "GATE" in load_prompt("Shipped")     # the packaged profile, not the stub


def test_the_shared_base_is_reachable_by_default():
    # a silent "" here would drop the whole shared prompt and fall back to
    # ranker.DEFAULT_SYSTEM without a word — the packaging failure mode we fixed
    assert len(load_prompt("NoSuchProfile")) > 1000
