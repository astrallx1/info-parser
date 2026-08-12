import copy
import os
import re

import yaml
from dotenv import load_dotenv
from topicparser import i18n, paths

# Load `.env` from beside the app, not by walking up from the CWD: a packaged app
# started from a shortcut has an arbitrary working directory and would silently run
# with no API keys at all.
load_dotenv(paths.resolve(".env"))

def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_path(name: str, default: str = "") -> str:
    """A path knob from `.env`, anchored to the app when it is relative."""
    return paths.resolve(env(name, default))


def env_num(name: str, default, cast=int):
    """A numeric knob that FALLS BACK instead of raising — the same promise
    `tuning.read` makes for the knobs on the Settings screen, for the ones that are
    deliberately not there. A bare `int(env(...))` meant one typo in a hand-edited
    `.env` stopped the app before its window ever opened, with nothing on screen to
    say why."""
    try:
        return cast(os.environ[name])
    except (KeyError, TypeError, ValueError):
        return default

# What a fresh install starts with. An example yaml used to sit in the repo but nothing
# ever copied it, so a new user landed on "no profiles, add one in the Profiles tab":
# nothing to run, and no example of what a source even looks like. Deliberately
# small — one profile, two accounts, no rules — so it shows the SHAPE without pretending
# to be tuned for anybody.
SEED_PROFILES = {
    "profiles": {
        "AI": {
            # GitHub is the source with the lowest barrier — a token with no scopes,
            # no cookies, no browser — and the guide invites the user to skip the X
            # step, so an empty list left the one source everybody has producing
            # nothing on the documented happy path. Three broad, real tags, checked
            # against the live API the same way the feeds below were: they match
            # 42 900 / 38 500 / 26 800 repositories created in the last 90 days. They
            # are the NET, not taste — the scoring prompt is what judges.
            "github": {"topics": ["llm", "ai-agents", "mcp"]},
            "x": {"accounts": ["OpenAI", "AnthropicAI"], "lists": [], "searches": []},
            # The third source shipped with an empty field, so a fresh install ran on
            # GitHub and X only. Three addresses, all checked against the real thing:
            # two lab blogs, and Anthropic's YouTube channel because Anthropic
            # publishes no RSS anywhere.
            "feeds": {"urls": [
                "https://openai.com/news/rss.xml",
                "https://blog.google/technology/ai/rss/",
                "https://www.youtube.com/feeds/videos.xml?channel_id=UCrDwWp7EBBv4NwvScIpBDOA",
            ]},
        }
    }
}


def _seed_prompts(profiles: dict) -> None:
    """Give each seeded profile the STARTER rules, written beside the app.

    A profile prompt is NOT shipped — the author's own rules stay in his own copy —
    so a seeded profile has nothing to score with until this writes the starter rules
    beside the app. Without this, a fresh install would silently start scoring
    by somebody else's rules under a profile the user thinks is theirs. A prompt beside
    the app wins over the packaged one (see `prompts_loader.prompts_dir`), so writing
    the starter there is what makes the seeded profile genuinely blank.
    """
    from topicparser import prompts_loader

    starter = prompts_loader.read_prompt("_starter") or "SCORE every signal 0-100."
    for name in profiles:
        own = os.path.join(prompts_loader.write_dir(), f"{name}.txt")
        if not os.path.exists(own):
            prompts_loader.save_profile_prompt(name, starter)


def load_profiles(path: str) -> dict:
    if not os.path.exists(path):
        seed = copy.deepcopy(SEED_PROFILES)
        try:
            save_profiles(path, seed)      # so the next launch reads a real file
            _seed_prompts(seed["profiles"])
        except OSError:
            pass                           # read-only install: still hand back the seed
        return seed
    with open(path, "r", encoding="utf-8") as f:
        # An emptied file is a CHOICE — deleting every profile must not be undone on the
        # next launch, so only a missing file seeds.
        return yaml.safe_load(f) or {"profiles": {}}

def save_profiles(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

PROFILE_NAME_MAX = 64

# Reserved on Windows whatever the extension: `CON.txt` is not a file there, and the
# owner's other machine runs Windows.
_WINDOWS_DEVICES = {"con", "prn", "aux", "nul",
                    *(f"com{i}" for i in range(1, 10)),
                    *(f"lpt{i}" for i in range(1, 10))}


def validate_profile_name(name: str) -> list[str]:
    """A profile name becomes `<name>.txt` in the prompts folder, so it is a FILENAME
    before it is a label. Everything here exists to keep a name from reaching outside
    that folder or colliding with the shared prompts that hold the machinery."""
    errs: list[str] = []
    if not isinstance(name, str) or not name.strip():
        return [i18n.t("err.name_empty")]
    if len(name) > PROFILE_NAME_MAX:
        errs.append(i18n.t("err.name_too_long", max=PROFILE_NAME_MAX))
    if any(ord(c) < 32 or ord(c) == 127 for c in name):
        errs.append(i18n.t("err.name_control_char"))
    # `/` and `\` escape the folder; the rest are simply illegal in a Windows filename,
    # so the name saved fine on the Mac and the profile could not be created at all on
    # the owner's normal machine — the half of the check that was missing.
    if any(c in name for c in '/\\:*?"<>|'):
        errs.append(i18n.t("err.name_separator"))
    if name.strip(". ") != name:
        # a leading/trailing dot or space: "." and ".." escape, and Windows silently
        # strips a trailing one, so "AI " and "AI" would fight over the same file
        errs.append(i18n.t("err.name_dot_space"))
    if name.split(".")[0].lower() in _WINDOWS_DEVICES:
        errs.append(i18n.t("err.name_reserved_windows"))
    if name.startswith("_"):
        errs.append(i18n.t("err.name_underscore"))
    return errs


# Every source except a search is an IDENTIFIER with a narrow, ASCII-only shape. None
# of this was checked, so a Cyrillic handle could be typed, saved, listed in the picker
# and then RUN — the scrape spent minutes on a URL that cannot exist. A search is a
# query rather than an identifier, so it stays free text.
_HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")          # X: letters, digits, underscore
_LIST_ID = re.compile(r"^\d+$")
_GH_TOPIC = re.compile(r"^[a-z0-9][a-z0-9-]{0,49}$")   # GitHub: lowercase, hyphenated


def _check_sources(name: str, cfg: dict) -> list[str]:
    errs: list[str] = []

    def bad(kind, value):
        errs.append(i18n.t("err.bad_source", name=name,
                           kind=i18n.t(f"source.kind_{kind}"), value=value))

    x = cfg.get("x") or {}
    for h in x.get("accounts") or []:
        if not _HANDLE.match(str(h or "")):
            bad("account", h)
    for entry in x.get("lists") or []:
        ident = entry.get("id") if isinstance(entry, dict) else entry
        if not _LIST_ID.match(str(ident or "")):
            bad("list", ident)
    for q in x.get("searches") or []:
        if not str(q or "").strip():
            bad("search", q)
    for t in (cfg.get("github") or {}).get("topics") or []:
        if not _GH_TOPIC.match(str(t or "")):
            bad("topic", t)
    # a feed is fetched with requests; anything but http(s) is either a mistake or a
    # way to make the app read a local file
    for u in (cfg.get("feeds") or {}).get("urls") or []:
        if not str(u or "").strip().lower().startswith(("http://", "https://")):
            bad("feed", u)
    return errs


def validate_profiles(data: dict) -> list[str]:
    errs: list[str] = []
    profiles = (data or {}).get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        return [i18n.t("err.no_profiles")]
    for name, cfg in profiles.items():
        if not isinstance(cfg, dict) or not ({"github", "x", "feeds"} & set(cfg)):
            errs.append(i18n.t("err.profile_no_source", name=name))
            continue
        errs += _check_sources(name, cfg)
    return errs
