"""A knob line carries the comment that explains it, and Save used to eat it.

`write_env` rewrites a line it owns as `KEY=value`, so the inline `# what this does`
after the value is gone. The Settings screen sends all nine tuning knobs at once, so
ONE save strips the explanation from every one of them, and `.env.example` promises the
opposite in as many words."""
from topicparser import settings


def test_saving_a_knob_keeps_its_inline_comment(tmp_path):
    p = tmp_path / ".env"
    p.write_text("SCORE_THRESHOLD=70            # a topic must score >= this\n",
                 encoding="utf-8")
    settings.write_env(str(p), {"SCORE_THRESHOLD": "80"})
    line = p.read_text(encoding="utf-8").strip()
    assert line.startswith("SCORE_THRESHOLD=80")
    assert "# a topic must score >= this" in line
    assert settings.read_env(str(p))["SCORE_THRESHOLD"] == "80"


def test_a_line_without_a_comment_stays_bare(tmp_path):
    p = tmp_path / ".env"
    p.write_text("OPENAI_API_KEY=old\n", encoding="utf-8")
    settings.write_env(str(p), {"OPENAI_API_KEY": "new"})
    assert p.read_text(encoding="utf-8").strip() == "OPENAI_API_KEY=new"


def test_a_hash_inside_a_quoted_value_is_not_a_comment(tmp_path):
    p = tmp_path / ".env"
    p.write_text('OFF_INTEREST="c#, f#"   # subjects to drop\n', encoding="utf-8")
    settings.write_env(str(p), {"OFF_INTEREST": "rust"})
    line = p.read_text(encoding="utf-8").strip()
    assert "# subjects to drop" in line
    assert settings.read_env(str(p))["OFF_INTEREST"] == "rust"


# --- a duplicated key ------------------------------------------------------------
#
# `.env` is a hand-edited file, so the same key ends up in it twice. Every reader
# (`read_env`, and dotenv underneath `config`) lets the LAST line win; `write_env`
# rewrote the FIRST. One Save from the Settings screen reported success, and the next
# launch read the stale duplicate below it.


def test_a_duplicated_key_is_written_where_the_readers_look(tmp_path):
    p = tmp_path / ".env"
    p.write_text("SCORE_THRESHOLD=55\nGH_PER_PAGE=100\nSCORE_THRESHOLD=70\n",
                 encoding="utf-8")

    settings.write_env(str(p), {"SCORE_THRESHOLD": "80"})

    assert settings.read_env(str(p))["SCORE_THRESHOLD"] == "80"


def test_the_shadowed_duplicate_is_left_alone(tmp_path):
    """It is dead as far as every reader is concerned, and removing a line the user
    typed is not this function's job: it promises to keep everything it does not own."""
    p = tmp_path / ".env"
    p.write_text("SCORE_THRESHOLD=55\nSCORE_THRESHOLD=70\n", encoding="utf-8")

    settings.write_env(str(p), {"SCORE_THRESHOLD": "80"})

    assert p.read_text(encoding="utf-8").splitlines() == ["SCORE_THRESHOLD=55",
                                                          "SCORE_THRESHOLD=80"]


def test_the_comment_of_the_line_actually_written_is_kept(tmp_path):
    p = tmp_path / ".env"
    p.write_text("X_MAX_TWEETS=75   # an old copy\n"
                 "X_MAX_TWEETS=150  # tweets per X source\n", encoding="utf-8")

    settings.write_env(str(p), {"X_MAX_TWEETS": "200"})

    lines = p.read_text(encoding="utf-8").splitlines()
    assert lines[1] == "X_MAX_TWEETS=200  # tweets per X source"
    assert lines[0] == "X_MAX_TWEETS=75   # an old copy"


# --- a quote inside a value ------------------------------------------------------
#
# `_format` quotes a value that carries a space, and `.env` has no escape for a quote
# inside quotes — so `say "hi", crypto` was written as `OFF_INTEREST="say "hi", crypto"`
# and read back as `say `. `OFF_INTEREST` is free text typed into the Settings screen,
# so this is a reachable way to silently lose most of a saved value.


def test_a_value_carrying_a_double_quote_survives_the_round_trip(tmp_path):
    p = tmp_path / ".env"
    p.write_text("OFF_INTEREST=\n", encoding="utf-8")

    settings.write_env(str(p), {"OFF_INTEREST": 'say "hi", crypto'})

    assert settings.read_env(str(p))["OFF_INTEREST"] == 'say "hi", crypto'


def test_a_value_carrying_a_single_quote_survives_too(tmp_path):
    p = tmp_path / ".env"
    p.write_text("OFF_INTEREST=\n", encoding="utf-8")

    settings.write_env(str(p), {"OFF_INTEREST": "what's new, crypto"})

    assert settings.read_env(str(p))["OFF_INTEREST"] == "what's new, crypto"
