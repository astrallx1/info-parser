"""The .md header was the last English left in a Ukrainian export.

Every section inside the file already came from the catalogue (TWITTER / GITHUB /
TRENDING, the `N з GitHub` summary, the velocity unit), but the H1 and the
empty-file line were literals: a Ukrainian user's file opened with
`# Topics — 2026-08-09`.
"""
import re

from tests.conftest import needs_uk
from topicparser import export, i18n


@needs_uk
def test_both_catalogues_carry_the_header_strings():
    for lang in ("uk", "en"):
        assert "{date}" in i18n.t("md.title", lang=lang)
        assert i18n.t("md.empty", lang=lang) != "md.empty"


@needs_uk
def test_header_comes_from_the_catalogue(monkeypatch):
    monkeypatch.setattr(i18n, "default_lang", lambda: "uk")
    md = export.to_markdown([{"title": "T", "why": "W", "score": 80,
                              "links": ["https://github.com/x/y"], "kept": 1}],
                            date="2026-08-09")
    assert md.startswith("# " + i18n.t("md.title", date="2026-08-09"))
    assert "Topics" not in md.splitlines()[0]


@needs_uk
def test_empty_file_line_comes_from_the_catalogue(monkeypatch):
    monkeypatch.setattr(i18n, "default_lang", lambda: "uk")
    md = export.to_markdown([], date="2026-08-09")
    assert i18n.t("md.empty") in md
    assert "topic(s)" not in md


@needs_uk
def test_no_long_dash_in_the_exported_header():
    """Long dashes were cleared out of every user-visible string; the file the owner
    opens every day is one."""
    for lang in ("uk", "en"):
        assert "—" not in i18n.t("md.title", lang=lang)


@needs_uk
def test_score_label_comes_from_the_catalogue(monkeypatch):
    """`score 85` was the other English literal in the file — same class as the H1."""
    monkeypatch.setattr(i18n, "default_lang", lambda: "uk")
    md = export.to_markdown([{"title": "T", "why": "W", "score": 85,
                              "links": ["https://github.com/x/y"], "kept": 1}],
                            date="2026-08-09")
    assert i18n.t("md.score", score=85) in md
    assert "score 85" not in md
