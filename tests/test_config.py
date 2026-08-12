import topicparser.config as config

VALID = {"profiles": {"AI": {"github": {"topics": ["mcp"], "keywords": ["agent"]}}}}

def test_validate_ok():
    assert config.validate_profiles(VALID) == []

def test_validate_reports_missing_sources():
    errs = config.validate_profiles({"profiles": {"AI": {}}})
    assert any("AI" in e for e in errs)

def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "profiles.yaml"
    config.save_profiles(str(p), VALID)
    assert config.load_profiles(str(p)) == VALID


# --- a typo in `.env` must not make the app unstartable ---------------------------
# `tuning.read` already promises this for the knobs on the Settings screen, but
# `main.py` cast the rest with a bare `int(...)` / `float(...)`, so one bad line meant
# the window never opened — no error, no app. And `.env.example` invites hand-editing.

def test_env_num_falls_back_when_the_value_is_not_a_number(monkeypatch):
    monkeypatch.setenv("X_MAX_SCROLLS", "abc")
    assert config.env_num("X_MAX_SCROLLS", 40) == 40


def test_env_num_falls_back_when_the_value_is_empty(monkeypatch):
    monkeypatch.setenv("X_MAX_SCROLLS", "")
    assert config.env_num("X_MAX_SCROLLS", 40) == 40


def test_env_num_reads_a_good_value(monkeypatch):
    monkeypatch.setenv("X_MAX_SCROLLS", "12")
    assert config.env_num("X_MAX_SCROLLS", 40) == 12


def test_env_num_casts_floats(monkeypatch):
    monkeypatch.setenv("X_MIN_DELAY", "2.5")
    assert config.env_num("X_MIN_DELAY", 3.0, float) == 2.5


def test_env_num_falls_back_when_the_variable_is_absent(monkeypatch):
    monkeypatch.delenv("X_MAX_SCROLLS", raising=False)
    assert config.env_num("X_MAX_SCROLLS", 40) == 40
