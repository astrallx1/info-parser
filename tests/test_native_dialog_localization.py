"""The buttons pywebview draws itself were the only English left on screen.

`confirm()` (ban, delete a profile, stop a run) and `prompt()` (new profile, rename)
are drawn by the platform through pywebview, which labels them from its OWN string
table — so a Ukrainian app asked "Забанити це репо?" over OK / Cancel. Same for the
title of the .md save dialog.
"""
import re

import main
from topicparser import i18n


def test_localization_maps_pywebview_keys_to_the_catalogue(monkeypatch):
    monkeypatch.setattr(i18n, "default_lang", lambda: "uk")
    loc = main.build_localization()
    assert loc["global.ok"] == i18n.t("dialog.ok")
    assert loc["global.cancel"] == i18n.t("dialog.cancel")
    assert loc["global.saveFile"] == i18n.t("dialog.save_file")
    assert all(v and v.strip() for v in loc.values())


def test_the_keys_it_uses_really_exist_in_pywebview():
    """A typo here would be silent — pywebview just keeps its English default."""
    from webview.localization import original_localization
    for key in main.build_localization():
        assert key in original_localization, key


def test_both_catalogues_carry_the_dialog_strings():
    for lang in ("uk", "en"):
        for key in ("dialog.ok", "dialog.cancel", "dialog.save_file"):
            assert i18n.t(key, lang=lang) != key


def test_main_hands_the_table_to_webview_start():
    src = open("main.py", encoding="utf-8").read()
    assert re.search(r"webview\.start\([^)]*localization=", src, re.S)
