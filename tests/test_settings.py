"""Writing `.env` from the app.

Editing a dotfile by hand is the first wall a non-programmer hits, so the app writes
it. That means rewriting a file the user also edits by hand, which is why every test
here is about NOT destroying what is already in it.
"""
import os
import stat
import sys

import pytest

from topicparser import settings

ENV = """# Secrets
GITHUB_TOKEN=old_gh
OPENAI_API_KEY=old_oai
LLM_MODEL=gpt-4.1-mini        # deliberately cheap

# Scoring
SCORE_THRESHOLD=70
"""


@pytest.fixture
def env(tmp_path):
    p = tmp_path / ".env"
    p.write_text(ENV, encoding="utf-8")
    return p


def test_reading_returns_the_values(env):
    got = settings.read_env(str(env))
    assert got["GITHUB_TOKEN"] == "old_gh"
    assert got["LLM_MODEL"] == "gpt-4.1-mini"      # the trailing comment is not a value


def test_writing_replaces_only_the_keys_given(env):
    settings.write_env(str(env), {"GITHUB_TOKEN": "new_gh"})
    text = env.read_text(encoding="utf-8")
    assert "GITHUB_TOKEN=new_gh" in text
    assert "OPENAI_API_KEY=old_oai" in text
    assert "SCORE_THRESHOLD=70" in text


def test_comments_and_order_survive_a_write(env):
    settings.write_env(str(env), {"GITHUB_TOKEN": "new_gh"})
    lines = env.read_text(encoding="utf-8").split("\n")
    assert lines[0] == "# Secrets"
    assert "# Scoring" in lines
    # the inline comment on a line we did not touch stays put
    assert any(l.startswith("LLM_MODEL=") and "deliberately cheap" in l for l in lines)


def test_a_new_key_is_appended(env):
    settings.write_env(str(env), {"APP_LANG": "uk"})
    assert "APP_LANG=uk" in env.read_text(encoding="utf-8")


def test_writing_to_a_missing_file_creates_it(tmp_path):
    p = tmp_path / ".env"
    settings.write_env(str(p), {"GITHUB_TOKEN": "x"})
    assert p.read_text(encoding="utf-8").strip() == "GITHUB_TOKEN=x"


@pytest.mark.skipif(sys.platform == "win32",
                    reason="POSIX modes do not exist on Windows; write_env guards the "
                           "chmod and the ACL is the user's own by default")
def test_the_file_is_not_world_readable(env):
    settings.write_env(str(env), {"GITHUB_TOKEN": "new_gh"})
    mode = stat.S_IMODE(os.stat(env).st_mode)
    assert mode & 0o077 == 0        # API keys in plain text: at least keep them private


def test_a_value_with_spaces_is_quoted_on_write(env):
    settings.write_env(str(env), {"OFF_INTEREST": "novabyte, some thing"})
    assert 'OFF_INTEREST="novabyte, some thing"' in env.read_text(encoding="utf-8")


def test_masking_shows_the_shape_without_the_secret():
    assert settings.mask("sk-proj-abcdefghijklmnop") == "sk-p…mnop"
    assert settings.mask("short") == "…"
    assert settings.mask("") == ""


def test_the_live_process_sees_a_saved_value_without_a_restart(env, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    settings.write_env(str(env), {"GITHUB_TOKEN": "fresh"})
    assert os.environ["GITHUB_TOKEN"] == "fresh"
