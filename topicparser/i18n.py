"""User-visible strings, one JSON catalogue per language.

ONE catalogue serves both Python and the UI — the browser side pulls it through
`Api.get_strings()` rather than keeping a second copy that can drift out of sync.

Resolution mirrors `prompts_loader`: a `lang/` folder beside the app wins over the
packaged copy, and a partial external file only overrides the keys it defines. That
is what lets the owner keep a Ukrainian build with no Ukrainian in the public repo —
his `lang/uk.json` lives beside the app and is never committed.
"""
import json
import os

from dotenv import load_dotenv

from topicparser import paths

# Explicitly, like config/store: dotenv's upward walk from the CWD is wrong for a
# shortcut-launched build, and the language must not depend on import order.
load_dotenv(paths.resolve(".env"))

_PACKAGED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lang")
_FALLBACK = "en"
_cache: dict[str, dict] = {}


def default_lang() -> str:
    return (os.getenv("APP_LANG") or _FALLBACK).strip().lower() or _FALLBACK


def _load_file(directory: str, code: str) -> dict:
    path = os.path.join(directory, f"{code}.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}          # a hand-edited catalogue must never take the app down


def strings(lang: str | None = None) -> dict:
    code = (lang or default_lang()).strip().lower()
    if code in _cache:
        return _cache[code]

    external = os.path.join(paths.app_dir(), "lang")
    merged = dict(_load_file(_PACKAGED, _FALLBACK))
    merged.update(_load_file(external, _FALLBACK))
    if code != _FALLBACK:
        # English underneath, so a key the translator has not reached yet still reads
        # as a sentence instead of a raw dotted key in the middle of the interface
        merged.update(_load_file(_PACKAGED, code))
        merged.update(_load_file(external, code))
    _cache[code] = merged
    return merged


def t(key: str, lang: str | None = None, **fmt) -> str:
    value = strings(lang).get(key)
    if not isinstance(value, str):
        return key
    try:
        return value.format(**fmt) if fmt else value
    except (KeyError, IndexError):
        return value


def _plural_form(code: str, n: int) -> str:
    """Which of one/few/many a count takes. English has two forms; Ukrainian picks by
    the LAST DIGIT with 11-14 excepted, which a single plural form gets wrong."""
    if code.startswith("uk") or code.startswith("ru"):
        if 11 <= n % 100 <= 14:
            return "many"
        last = n % 10
        return "one" if last == 1 else "few" if 2 <= last <= 4 else "many"
    return "one" if n == 1 else "many"


def plural(key: str, n: int, lang: str | None = None) -> str:
    code = (lang or default_lang()).strip().lower()
    forms = strings(code).get(f"plural.{key}")
    if not isinstance(forms, dict):
        return f"{n}"
    form = _plural_form(code, n)
    template = forms.get(form) or forms.get("many") or forms.get("one") or "{n}"
    return template.format(n=n)
