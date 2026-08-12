import os

import pytest

from topicparser import i18n

# The Ukrainian catalogue is the OWNER's file and lives only in the private repo, so a
# test that asserts on Ukrainian output has nothing to assert against in the public
# copy. Those tests are marked with `needs_uk` and skip there instead of going red.
UK_CATALOGUE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "lang", "uk.json")
needs_uk = pytest.mark.skipif(not os.path.exists(UK_CATALOGUE),
                              reason="lang/uk.json is private to the owner's build")


@pytest.fixture(autouse=True)
def _pin_language(monkeypatch):
    """Run the suite in English whatever the developer's `.env` says.

    `i18n` loads `.env` on import (deliberately — a shortcut-launched build cannot
    rely on dotenv walking up from the CWD), so an owner running with APP_LANG=uk
    would otherwise see a dozen assertions fail on his machine and nowhere else.
    The cache is cleared too: it is keyed by code, but a test that points `app_dir`
    at a tmp folder must not inherit a catalogue read from the real one.
    """
    monkeypatch.setenv("APP_LANG", "en")
    monkeypatch.setattr(i18n, "_cache", {})


@pytest.fixture(autouse=True)
def _pin_tuning(monkeypatch):
    """Same reason as the language, and now it matters more.

    `Api` resolves every knob at RUN time so a value saved in Settings reaches the next
    run, and `.env` wins over what the Api was constructed with. The owner's `.env`
    carries real values, so without this a test that builds an `Api` with
    `threshold=80` would silently run at his threshold instead — green here, green in
    the public copy (which has no `.env` at all), and wrong on his machine only.
    """
    from topicparser import tuning

    for knob in tuning.KNOBS:
        monkeypatch.delenv(knob.name, raising=False)


@pytest.fixture
def cyrillic_lang(monkeypatch):
    """A synthetic Cyrillic-script language, so the reason-repair tests prove the
    behaviour without needing the owner's catalogue on disk. They used to pass
    `lang="uk"` and therefore only worked in the private repo."""
    code = "zz"
    cache = dict(i18n._cache)
    cache[code] = {"lang.name": "Ukrainian", "lang.script": "cyrillic"}
    monkeypatch.setattr(i18n, "_cache", cache)
    return code


@pytest.fixture
def packaged_prompts(tmp_path, monkeypatch):
    """A stand-in for the prompts shipped INSIDE the build, holding one profile.

    Several tests used the owner's own `AI.txt` as "a packaged profile prompt". It is
    excluded from the public copy by `publish.sh`, so they went red there — and they
    were never really about his rules, only about a profile whose file lives in the
    build rather than beside the app.
    """
    from topicparser import prompts_loader as pl

    packaged = tmp_path / "packaged"
    packaged.mkdir()
    for name in ("_base.txt", "_group.txt", "_dedup.txt", "_xgate.txt",
                 "_language.en.txt", "_starter.txt"):
        src = os.path.join(pl._PACKAGED, name)
        if os.path.exists(src):
            (packaged / name).write_text(open(src, encoding="utf-8").read(),
                                         encoding="utf-8")
    (packaged / "Shipped.txt").write_text("GATE A -> 45\n", encoding="utf-8")
    monkeypatch.setattr(pl, "_PACKAGED", str(packaged))
    return packaged
