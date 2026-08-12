"""The tuning knobs, declared once.

They used to exist only as `.env` lines read at `Api` construction, which meant two
things: you had to find a dotfile to change how the tool judges anything, and a change
did not reach the running app. This module is the single declaration — the Settings
screen renders it, `Api` validates against it, and the run resolves through it, so the
three cannot drift.

Deliberately NOT here: `LLM_BATCH_SIZE` (a reliability dial the gap-fill is tuned
against), the scrape pacing (`X_MIN_DELAY`/`X_MAX_DELAY`/`X_MAX_SCROLLS`) and
Getting those wrong gets the X account rate-limited or banned, and
none of them is a judgement the owner wants to make from a form.
"""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Knob:
    name: str
    kind: str                       # "int" | "float" | "text"
    default: object
    minimum: Optional[float] = None
    maximum: Optional[float] = None


# Order is the order they render in.
KNOBS = [
    Knob("SCORE_THRESHOLD", "int", 70, 0, 100),
    Knob("GH_PER_PAGE", "int", 100, 1, 100),          # GitHub answers 422 above 100
    Knob("X_MAX_TWEETS", "int", 150, 1, 500),
    Knob("GH_FRESH_DAYS", "int", 60, 1, 365),
    Knob("X_FRESH_DAYS", "int", 3, 1, 90),
    Knob("FEED_FRESH_DAYS", "int", 7, 1, 90),
    Knob("TREND_MIN_VELOCITY", "float", 50, 1, 100000),
    Knob("TRACK_STAGNANT_DAYS", "int", 21, 1, 365),
    # Empty on purpose: which subjects a reader never covers is their own call, and a
    # shipped list would quietly drop signals they never asked to lose.
    Knob("OFF_INTEREST", "text", ""),
]

BY_NAME = {k.name: k for k in KNOBS}


def _coerce(knob: Knob, raw):
    if knob.kind == "text":
        return "" if raw is None else str(raw)
    try:
        value = int(raw) if knob.kind == "int" else float(raw)
    except (TypeError, ValueError):
        return None
    if knob.minimum is not None and value < knob.minimum:
        return None
    if knob.maximum is not None and value > knob.maximum:
        return None
    return value


def read(defaults: dict | None = None) -> dict:
    """Resolve every knob: the environment first, then the caller's own defaults, then
    the declared one. A value that will not parse falls back rather than killing the
    run — a typo in `.env` must not make the app unstartable.

    `defaults` is what `Api` was constructed with, so a test that builds an `Api` with
    `threshold=80` keeps it while a real `.env` still wins.
    """
    defaults = defaults or {}
    out = {}
    for knob in KNOBS:
        value = None
        if knob.name in os.environ:
            value = _coerce(knob, os.environ[knob.name])
        if value is None and knob.name in defaults:
            value = _coerce(knob, defaults[knob.name])
        if value is None:
            value = knob.default
        out[knob.name] = value
    return out


def validate(values: dict) -> list[str]:
    """Problems, empty when the set is writable. Refuses an unknown name outright:
    this screen writes `.env` and must not become a way to set any variable."""
    from topicparser import i18n

    errs = []
    for name, raw in (values or {}).items():
        knob = BY_NAME.get(name)
        if knob is None:
            errs.append(i18n.t("err.not_a_knob", name=name))
            continue
        if knob.kind == "text":
            # `.env` quotes a value carrying a space and has no escape for a quote
            # inside the quotes, so one kind can be the wrapper and the other the
            # content, but not both. Refusing beats writing a value that reads back
            # truncated at the first inner quote.
            if '"' in str(raw or "") and "'" in str(raw or ""):
                errs.append(i18n.t("err.knob_quotes",
                                   label=i18n.t(f"tune.{knob.name}")))
            # `.env` is line-based, so a newline inside a value is not a value at all:
            # everything after it is read back as another KEY. `OFF_INTEREST` carrying
            # "crypto\nGITHUB_TOKEN=..." rewrote the token, which is exactly what the
            # writer's own comment promises cannot happen. The UI's single-line input
            # strips them; the bridge is not the UI.
            elif any(c in str(raw or "") for c in "\r\n"):
                errs.append(i18n.t("err.knob_newline",
                                   label=i18n.t(f"tune.{knob.name}")))
            continue
        if _coerce(knob, raw) is None:
            # the LABEL, not the variable name: the message lands in a toast next to
            # the field the reader is looking at
            label = i18n.t(f"tune.{knob.name}")
            errs.append(i18n.t("err.knob_range", label=label,
                               min=_plain(knob.minimum), max=_plain(knob.maximum)))
    return errs


def _plain(n):
    return int(n) if float(n).is_integer() else n


def for_env(values: dict) -> dict:
    """What to hand `settings.write_env`. Everything is a string there, and an EMPTY
    text knob must survive: clearing `OFF_INTEREST` means "nothing is off-interest",
    which `save_settings`' "a blank field means leave it" rule would otherwise eat."""
    return {name: ("" if raw is None else str(raw))
            for name, raw in (values or {}).items() if name in BY_NAME}


def off_interest_terms(values: dict) -> set[str]:
    return {t.strip().lower() for t in str(values.get("OFF_INTEREST") or "").split(",")
            if t.strip()}
