import json

import pytest

from topicparser import i18n


def _catalogue(tmp_path, code, data):
    d = tmp_path / "lang"
    d.mkdir(exist_ok=True)
    (d / f"{code}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_default_lang_is_english_when_unset(monkeypatch):
    monkeypatch.delenv("APP_LANG", raising=False)
    assert i18n.default_lang() == "en"


def test_default_lang_reads_the_env_and_normalises_it(monkeypatch):
    monkeypatch.setenv("APP_LANG", " UK ")
    assert i18n.default_lang() == "uk"


def test_packaged_english_catalogue_covers_the_app(monkeypatch):
    monkeypatch.setattr(i18n, "_cache", {})
    s = i18n.strings("en")
    assert s["nav.feed"] and s["run.working"]
    assert not any("Ѐ" <= c <= "ӿ" for c in json.dumps(s, ensure_ascii=False))


def test_external_catalogue_beside_the_app_wins(tmp_path, monkeypatch):
    _catalogue(tmp_path, "en", {"nav.feed": "MY FEED"})
    monkeypatch.setattr(i18n.paths, "app_dir", lambda: str(tmp_path))
    monkeypatch.setattr(i18n, "_cache", {})
    assert i18n.strings("en")["nav.feed"] == "MY FEED"


def test_external_catalogue_only_overrides_the_keys_it_defines(tmp_path, monkeypatch):
    # a hand-written uk.json will always lag the shipped one; a missing key must fall
    # back to English rather than render as a raw key in the middle of the UI
    _catalogue(tmp_path, "uk", {"nav.feed": "Стрічка"})
    monkeypatch.setattr(i18n.paths, "app_dir", lambda: str(tmp_path))
    monkeypatch.setattr(i18n, "_cache", {})
    s = i18n.strings("uk")
    assert s["nav.feed"] == "Стрічка"
    assert s["run.working"] == i18n.strings("en")["run.working"]


def test_unknown_language_falls_back_to_english(monkeypatch):
    monkeypatch.setattr(i18n, "_cache", {})
    assert i18n.strings("xx") == i18n.strings("en")


def test_t_formats_placeholders(monkeypatch):
    monkeypatch.setattr(i18n, "_cache", {})
    assert i18n.t("run.error", "en", error="boom").endswith("boom")


def test_t_on_a_missing_key_returns_the_key(monkeypatch):
    monkeypatch.setattr(i18n, "_cache", {})
    assert i18n.t("no.such.key", "en") == "no.such.key"


@pytest.mark.parametrize("n,expected", [
    (0, "0 topics ready"), (1, "1 topic ready"), (2, "2 topics ready"),
    (5, "5 topics ready"), (11, "11 topics ready"), (21, "21 topics ready"),
])
def test_english_plural(n, expected, monkeypatch):
    monkeypatch.setattr(i18n, "_cache", {})
    assert i18n.plural("topics_ready", n, "en") == expected


@pytest.mark.parametrize("n,expected", [
    (1, "1 тема готова"), (2, "2 теми готові"), (4, "4 теми готові"),
    (5, "5 тем готово"), (11, "11 тем готово"), (12, "12 тем готово"),
    (14, "14 тем готово"), (21, "21 тема готова"), (22, "22 теми готові"),
    (25, "25 тем готово"), (0, "0 тем готово"),
])
def test_ukrainian_plural_declines_by_the_last_digit(n, expected, tmp_path, monkeypatch):
    _catalogue(tmp_path, "uk", {"plural.topics_ready": {
        "one": "{n} тема готова", "few": "{n} теми готові", "many": "{n} тем готово"}})
    monkeypatch.setattr(i18n.paths, "app_dir", lambda: str(tmp_path))
    monkeypatch.setattr(i18n, "_cache", {})
    assert i18n.plural("topics_ready", n, "uk") == expected
