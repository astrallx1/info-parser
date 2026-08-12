"""A star count must be grouped the way the rest of the build groups numbers.

The tracked table rendered `98,196` (hardcoded en-US) while the feed card and the
trending card rendered `98 196` (hardcoded uk) — the same number, two formats, one
screen apart. Both were hardcoded, so the English build got the Ukrainian grouping
too. The separator belongs in the catalogue, next to `locale.date`.
"""
import re

from tests.conftest import needs_uk
from topicparser import export, i18n


@needs_uk
def test_catalogues_declare_a_thousands_separator():
    assert i18n.t("locale.thousands", lang="uk") == " "   # non-breaking space
    assert i18n.t("locale.thousands", lang="en") == ","


@needs_uk
def test_md_stars_use_the_catalogue_separator(monkeypatch):
    monkeypatch.setattr(i18n, "default_lang", lambda: "uk")
    assert export._stars(98196) == "98 196"
    monkeypatch.setattr(i18n, "default_lang", lambda: "en")
    assert export._stars(98196) == "98,196"


def test_ui_never_hardcodes_a_number_locale():
    """The three toLocaleString calls (feed meta, trending card, tracked table) must
    all go through the catalogue, or one of them drifts again."""
    ui = open("topicparser/ui/index.html", encoding="utf-8").read()
    hardcoded = re.findall(r"toLocaleString\(\s*['\"][\w-]+['\"]", ui)
    assert hardcoded == [], f"hardcoded number locales: {hardcoded}"
    assert "function fmtNum" in ui
