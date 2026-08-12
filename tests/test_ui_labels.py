"""Every label on screen must come from the catalogue, and must describe what the
code actually does.

Two classes of bug this file locks down:

* `unwatch` and `unban` were written into the markup as bare English words, so the
  Ukrainian build showed «Бан» and `unwatch` side by side in the same table row.
* `field.topics_help` told the user GitHub results are "sorted by recently updated".
  The collector sorts by STARS over repos created in the last 90 days, and the
  comment above it says the `updated` sort was dropped on purpose because it floods
  the feed. A help line that describes the opposite of the code is worse than none.
"""
import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = open(os.path.join(ROOT, "topicparser", "ui", "index.html"), encoding="utf-8").read()

CATALOGUES = [os.path.join(ROOT, "topicparser", "lang", "en.json"),
              os.path.join(ROOT, "lang", "uk.json")]
PRESENT = [p for p in CATALOGUES if os.path.exists(p)]


def catalogue(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("key", ["tracked.unwatch", "banned.unban"])
def test_every_catalogue_carries_the_row_button_labels(key):
    for path in PRESENT:
        assert catalogue(path).get(key), f"{key} missing from {os.path.basename(path)}"


@pytest.mark.parametrize("word", ["unwatch", "unban"])
def test_the_row_buttons_are_not_hardcoded_english(word):
    """The literal may still appear as a data-attribute (`data-unwatch`) or a key —
    what must not appear is the bare word used as the button's text."""
    assert not re.search(r">\s*%s\s*<" % word, UI)
    assert ("}%s<" % word) not in UI


def test_the_github_help_does_not_claim_a_sort_the_collector_does_not_use():
    from topicparser.collectors import github

    src = open(github.__file__, encoding="utf-8").read()
    assert '"sort": "stars"' in src
    for path in PRESENT:
        help_text = catalogue(path).get("field.topics_help", "").lower()
        assert help_text
        for wrong in ("recently updated", "нещодавно оновлен"):
            assert wrong not in help_text, f"{os.path.basename(path)} still says '{wrong}'"


def test_trending_cards_offer_the_same_actions_as_a_github_card():
    """A trending repo is a post idea like any other and lands in the .md, but its
    card had no buttons at all — you could not copy it, and banning it meant hunting
    the repo down on the Відстеження screen."""
    block = UI[UI.index("function alertCard"):UI.index("function cardMeta")]
    assert 'data-act="copy"' in block
    assert 'data-act="ban"' in block
    assert 'data-act="open"' in block


def test_no_dead_about_keys_for_prompts_that_are_never_listed():
    """`prompts.about.<name>` is rendered for the files `Api.list_prompts` returns.
    `_language.*` is not one of them, so those two lines were unreachable text."""
    from topicparser import prompts_loader

    listed = {p["name"] for p in prompts_loader.list_prompts(["AI"])}
    for path in PRESENT:
        for key in catalogue(path):
            if key.startswith("prompts.about."):
                assert key[len("prompts.about."):] in listed, f"{key} is never shown"


def test_every_knob_has_a_label_and_a_help_line_in_every_catalogue():
    """Adding a knob to `tuning.KNOBS` without its strings renders a dotted key in the
    middle of Settings — the screen is generated from the declaration, so the two have
    to be added together."""
    from topicparser import tuning

    for path in PRESENT:
        cat = catalogue(path)
        for knob in tuning.KNOBS:
            for key in (f"tune.{knob.name}", f"tune.{knob.name}_help"):
                assert cat.get(key), f"{key} missing from {os.path.basename(path)}"


def test_no_error_message_is_a_bare_english_literal():
    """Every message the UI shows must come from a catalogue.

    `Api` used to return 27 English strings straight into a toast — "a profile named
    'AI' already exists", "the last profile cannot be deleted" — so a Ukrainian build
    spoke English the moment anything went wrong. The UI toasts `errors[0]` verbatim,
    so there is nowhere else this could be caught.
    """
    import re

    sources = ["topicparser/api.py", "topicparser/config.py",
               "topicparser/prompts_loader.py", "topicparser/tuning.py"]
    offenders = []
    for rel in sources:
        src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
        for m in re.finditer(r'(?:"error"|"errors")\s*:\s*\[?\s*(f?"[^"]{4,}")', src):
            offenders.append(f"{rel}: {m.group(1)}")
        for m in re.finditer(r'(?:errs\.append|return \[)\s*\(?(f?"[^"]{4,}")', src):
            offenders.append(f"{rel}: {m.group(1)}")
    assert offenders == [], "English literals returned to the UI: " + "; ".join(offenders)


def test_every_view_that_can_hold_an_unsaved_edit_guards_leaving_it():
    """Profiles asked before throwing an edit away; Settings did not, so a typed API
    key and a changed tuning knob both vanished on a nav click with no warning. The
    guard is a registry rather than an `if` per screen, so a screen added later has to
    opt in somewhere visible.
    """
    block = UI[UI.index("const VIEW_DIRTY"):UI.index("function showView")]
    for view in ("profiles", "settings"):
        assert f"{view}:" in block, f"{view} has no unsaved-edit guard"
    assert "profilesDirty()" in block and "settingsDirty()" in block
    # and showView must consult the registry, not a hardcoded view name
    show = UI[UI.index("function showView"):UI.index("/* ---- feed ---- */")]
    assert "VIEW_DIRTY[CURRENT_VIEW]" in show


def test_no_project_text_file_reads_as_binary():
    """A single NUL byte makes grep, and every other text tool, skip a file silently.
    It happened once in `index.html` (an escape written as the byte) and then again in
    CLAUDE.md — in the very sentence describing the first one.
    """
    import glob

    checked = (glob.glob(os.path.join(ROOT, "*.md"))
               + glob.glob(os.path.join(ROOT, "docs", "*.md"))
               + glob.glob(os.path.join(ROOT, "topicparser", "**", "*.html"), recursive=True)
               + glob.glob(os.path.join(ROOT, "topicparser", "**", "*.py"), recursive=True))
    offenders = [os.path.relpath(p, ROOT) for p in checked
                 if b"\x00" in open(p, "rb").read()]
    assert offenders == [], f"NUL bytes make these unsearchable: {offenders}"


# --- the feed starts empty, and stays that way until a run -------------------------


def test_the_feed_is_not_restored_on_launch():
    """Owner's call, 2026-09-04: he runs, reads, exports the `.md`, and THAT is the
    artifact. A previous run still on screen when the app opens reads as clutter, so
    the restore is gone — and with it the «clear» button, which only existed because
    a screen-only clear came straight back on the next launch."""
    for gone in ("restoreLastRun", "get_saved_topics", "FEED_CLEARED",
                 "setFeedCleared", "clearFeed", "clear-btn"):
        assert gone not in UI, f"the feed restore is back: {gone}"


@pytest.mark.parametrize("key", ["btn.clear_feed", "confirm.clear_feed"])
def test_the_clear_feed_strings_are_gone_from_every_catalogue(key):
    """A string no screen renders is a string a translator pays for."""
    for path in PRESENT:
        assert key not in catalogue(path), \
            f"{key} still in {os.path.basename(path)} with nothing rendering it"


def test_wiping_the_topics_still_empties_the_screen():
    """The one place cards must still be cleared: they would otherwise outlive the
    rows they came from and their keep checkbox would write to nothing."""
    body = UI[UI.index("if(parts.topics){"):]
    body = body[:body.index("}")]
    assert "$('#results').innerHTML = ''" in body
