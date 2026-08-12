import os
import re

from topicparser import paths
from topicparser import i18n
from topicparser.i18n import default_lang

# The prompts shipped with the code. Packaged, this resolves inside the bundle
# (PyInstaller's _MEIPASS), so it is read-only and disappears on the next build.
_PACKAGED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")


def prompts_dir() -> str:
    """Where to read scoring rules from.

    A `prompts/` folder sitting beside the app WINS. That is the whole point of
    keeping the rules outside the bundle: scoring is tuned by editing a `.txt`
    next to the `.exe`, with no repackaging. With nothing there we fall back to
    the copy shipped inside the build — which is also the from-source layout, so
    running from a checkout behaves exactly as it always did.
    """
    external = os.path.join(paths.app_dir(), "prompts")
    if os.path.isdir(external):
        return external
    return _PACKAGED


# alias so the loaders below can resolve the default while still exposing a
# `prompts_dir` PARAMETER (which would otherwise shadow the function name)
_default_dir = prompts_dir


def _read(prompts_dir: str, name: str) -> str:
    """Read one prompt file. The external folder wins PER FILE, not wholesale: the
    owner keeps a single `_language.uk.txt` outside the package, and all-or-nothing
    resolution would hide every other packaged prompt and silently gut scoring."""
    for d in ([prompts_dir] if prompts_dir else [_default_dir(), _PACKAGED]):
        path = os.path.join(d, name)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
    return ""


def _language_sections(lang: str, prompts_dir: str | None) -> dict:
    """`_language.<code>.txt` split on its [[section]] markers. Unknown code falls
    back to English rather than dropping the rule — a scoring prompt with no language
    rule at all is how a third of the descriptions once came back in the wrong one."""
    raw = _read(prompts_dir, f"_language.{(lang or '').lower()}.txt")
    if not raw:
        raw = _read(prompts_dir, "_language.en.txt")
    out, key = {}, None
    for line in raw.split("\n"):
        m = re.match(r"^\[\[(\w+)\]\]$", line.strip())
        if m:
            key = m.group(1)
            out[key] = []
        elif key:
            out[key].append(line)
    return {k: "\n".join(v).strip("\n") for k, v in out.items()}


def load_base(lang: str | None = None, prompts_dir: str | None = None) -> str:
    """`_base.txt` with its language-dependent blocks filled in. The file itself holds
    only machinery and shared taste; the wording that names a language lives in
    `_language.<code>.txt`, which is what makes one build serve both."""
    base = _read(prompts_dir, "_base.txt")
    sections = _language_sections(lang if lang is not None else default_lang(), prompts_dir)
    for token, key in (("{{REASON_LANGUAGE}}", "reason"), ("{{TITLE_LANGUAGE}}", "title")):
        base = base.replace(token, sections.get(key, ""))
    return base.strip()


def load_prompt(profile_name: str, prompts_dir: str | None = None,
                lang: str | None = None) -> str:
    """Shared base (language-filled) + per-profile <name>.txt. Profile file optional."""
    base = load_base(lang=lang, prompts_dir=prompts_dir)
    prof = _read(prompts_dir, f"{profile_name}.txt")
    if prof:
        return f"{base}\n\n{prof}".strip()
    return base


def load_group_prompt(prompts_dir: str | None = None, lang: str | None = None) -> str:
    """Standalone grouping-pass prompt (_group.txt); not profile-specific. It writes
    the `why` the user reads, so it carries a language block of its own, filled from
    the same `_language.<code>.txt` fragment as the scoring prompt.
    Empty string when missing — ranker then falls back to its DEFAULT_GROUP."""
    raw = _read(prompts_dir, "_group.txt")
    if not raw:
        return ""
    sections = _language_sections(lang if lang is not None else default_lang(), prompts_dir)
    return raw.replace("{{GROUP_LANGUAGE}}", sections.get("group", "")).strip()


def load_dedup_prompt(prompts_dir: str | None = None) -> str:
    """Standalone cross-run dedup prompt (_dedup.txt); not profile-specific.
    Empty string when missing — ranker then falls back to its DEFAULT_DEDUP."""
    return _read(prompts_dir, "_dedup.txt")


# --- editing -------------------------------------------------------------------
# Shared prompts hold the machinery (the JSON contract, the clustering and gate
# questions). They are shown so a user can see how the thing decides, but not edited
# from the UI: a broken `_xgate.txt` costs a whole run, and the failure is silent.
SHARED_PROMPTS = ["_base", "_xgate", "_feedgate", "_group", "_dedup"]
# Not machinery: `_meta` is the text the owner pastes into ChatGPT next to a topic, so
# the pipeline never reads it. It used to be handed over on the last step of the
# first-run guide and was then unreachable; it lives on the Prompts screen now, and
# unlike the shared files above it is editable.
EDITABLE_EXTRAS = ["_meta"]


def _write_dir() -> str:
    """The path only. `write_dir` CREATES it, and `has_backup` used to go through that
    on its way to `_backup_path` — so merely opening the Prompts screen left an empty
    `prompts/` beside the app, which from source is the repo itself."""
    return os.path.join(paths.app_dir(), "prompts")


def write_dir() -> str:
    """Where an EDITED prompt goes: always the folder beside the app, never the
    packaged copy — that one is read-only in a frozen build and is replaced by the
    next release. Created on demand, since a fresh install has no such folder."""
    d = _write_dir()
    os.makedirs(d, exist_ok=True)
    return d


def read_prompt(name: str) -> str:
    """The RAW file behind a prompt — what the user is looking at, tokens and all,
    not the assembled text the model gets.

    A name becomes a FILENAME here, and this is the READ door: `save_profile_prompt`
    validated it and this did not, so `../secret` read `<app_dir>/../secret.txt`. A
    name that is not a bare filename reads as no prompt at all, the same as a missing
    file — the only other way a prompt can be absent."""
    if name != os.path.basename(name) or "\\" in name or name.startswith("."):
        return ""
    return _read(None, f"{name}.txt")


def list_prompts(profile_names: list[str]) -> list[dict]:
    rows = [{"name": n, "editable": True} for n in profile_names]
    rows += [{"name": n, "editable": True} for n in EDITABLE_EXTRAS]
    rows += [{"name": n, "editable": False} for n in SHARED_PROMPTS]
    return rows


def save_profile_prompt(name: str, text: str) -> list[str]:
    """Returns a list of problems, empty when written. Never raises at the caller."""
    from topicparser import config
    # the underscore names are reserved, but `_meta` is deliberately writable
    if name not in EDITABLE_EXTRAS:
        errs = config.validate_profile_name(name)
        if errs:
            return errs
    if not (text or "").strip():
        # an empty prompt does not fail loudly: the ranker falls back to its 14-line
        # stub and still produces a plausible-looking feed with all the tuning gone
        return [i18n.t("err.prompt_empty")]
    path = os.path.join(write_dir(), f"{name}.txt")
    # Keep the version being replaced. These files ARE the product — 33 KB of rules
    # tuned over months of replays — and a save used to overwrite them outright. An
    # empty save is refused above, but a three-character one is legal and would have
    # destroyed the lot with no way back.
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            previous = f.read()
        with open(_backup_path(name), "w", encoding="utf-8") as f:
            f.write(previous)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.strip())
    return []


def _backup_path(name: str) -> str:
    # `_write_dir`, not `write_dir`: this is on the read path too (`has_backup`), and
    # asking whether a backup exists must not create a folder
    return os.path.join(_write_dir(), f"{name}.bak.txt")


def has_backup(name: str) -> bool:
    return os.path.exists(_backup_path(name))


def restore_profile_prompt(name: str) -> list[str]:
    """Put the previous version back. SWAPS rather than discards, so restoring is
    itself undoable — pressing it by accident must not be the new one-way door."""
    if not has_backup(name):
        return [i18n.t("err.no_backup")]
    path = os.path.join(write_dir(), f"{name}.txt")
    with open(_backup_path(name), encoding="utf-8") as f:
        backup = f.read()
    current = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            current = f.read()
    with open(path, "w", encoding="utf-8") as f:
        f.write(backup)
    with open(_backup_path(name), "w", encoding="utf-8") as f:
        f.write(current)
    return []


def delete_profile_prompt(name: str) -> list[str]:
    from topicparser import config
    errs = config.validate_profile_name(name)
    if errs:
        return errs
    # the backup goes too: a profile recreated under the same name would otherwise be
    # offered "restore the previous version" and handed the deleted profile's rules
    for path in (os.path.join(write_dir(), f"{name}.txt"), _backup_path(name)):
        if os.path.exists(path):
            os.remove(path)
    return []      # a profile whose prompt was only ever the packaged one is fine


def copy_profile_prompt(old: str, new: str) -> list[str]:
    """The first half of a rename: `new` gets the rules, `old` keeps them.

    Split out so `Api.rename_profile` can put the yaml write BETWEEN the two halves.
    Whichever step fails then, both names still have a prompt — an orphan file costs
    nothing, while a profile the config still names and whose rules are gone scores on
    the ranker's stub and produces a plausible feed with all the tuning missing."""
    from topicparser import config
    errs = config.validate_profile_name(old) + config.validate_profile_name(new)
    if errs:
        return errs
    if os.path.exists(os.path.join(_write_dir(), f"{new}.txt")):
        return [i18n.t("err.prompt_exists", name=new)]
    text = read_prompt(old)          # through the packaged fallback
    if not text:
        return [i18n.t("err.prompt_not_found", name=old)]
    return save_profile_prompt(new, text)


def load_xgate_prompt(prompts_dir: str | None = None) -> str:
    """Standalone X-gate prompt (_xgate.txt); not profile-specific. Empty string
    when missing — the gate is then skipped entirely (no extra LLM call)."""
    return _read(prompts_dir, "_xgate.txt")


def load_feedgate_prompt(prompts_dir: str | None = None) -> str:
    """Standalone official-source gate (_feedgate.txt). Same contract as the X one:
    missing file means the gate is skipped and nothing is paid for."""
    return _read(prompts_dir, "_feedgate.txt")
