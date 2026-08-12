import os
import platform
import webview
from topicparser import i18n, tuning
from topicparser import store, config, paths
from topicparser.window import MIN_SIZE, geometry as window_geometry
from topicparser.api import Api
from topicparser.collectors.feeds import FeedCollector
from topicparser.collectors.github import GitHubCollector
from topicparser.collectors.x import XCollector
from topicparser.llm import OpenAIClient
from topicparser.prompts_loader import (load_prompt, load_group_prompt,
                                        load_dedup_prompt, load_xgate_prompt,
                                        load_feedgate_prompt)

def build_collectors():
    # The X collector is ALWAYS built. It used to be skipped when cookies.json was
    # absent, which made X vanish from the run without a word; now the missing file
    # raises on session open and reaches the user as a red warning banner.
    #
    # Called once per run, so the two collector knobs are read fresh — a value saved in
    # Settings applies to the next run, exactly like the ones `Api` resolves. They go
    # through `tuning` rather than `config.env` so the screen and the run share one
    # declaration (and one clamp).
    knobs = tuning.read()
    return [
        GitHubCollector(token=config.env("GITHUB_TOKEN"),
                        per_page=knobs["GH_PER_PAGE"],
                        # A CEILING on the search, not the freshness filter — which is
                        # why the knob may only lift it. Nothing passed it before, so
                        # GH_FRESH_DAYS could be set to a year and repos created more
                        # than 90 days ago still never arrived. Wiring it straight
                        # through would be worse than the bug: at the default 60 it
                        # would drop repos created 80 days ago and pushed yesterday,
                        # which are precisely the ones the 90 exists to catch.
                        created_within_days=max(90, knobs["GH_FRESH_DAYS"])),
        # No key, no browser, no rate limit — the first-party channel. A profile with
        # no feeds configured makes it a no-op, so it costs nothing to always build.
        FeedCollector(),
        XCollector(
            cookies_path=config.env_path("COOKIES_PATH", "./cookies.json"),
            limit=knobs["X_MAX_TWEETS"],
            # the pacing knobs are off the Settings screen on purpose (getting them
            # wrong gets the X account limited), but they are still hand-edited, so
            # they fall back rather than killing the run
            min_delay=config.env_num("X_MIN_DELAY", 3.0, float),
            max_delay=config.env_num("X_MAX_DELAY", 8.0, float),
            # These fallbacks are what a fresh install with no `.env` runs on, so they
            # mirror `.env.example` — pinned by a test, because they drifted: the
            # scroll ceiling was measured and raised to 80 while this still said 40.
            max_scrolls=config.env_num("X_MAX_SCROLLS", 80)),
    ]

def build_client():
    return OpenAIClient.from_env(api_key=config.env("OPENAI_API_KEY"),
                                 model=config.env("LLM_MODEL", "gpt-4.1-mini"))

def build_localization():
    """The strings pywebview draws ITSELF, out of the app's own catalogue.

    `confirm()` and `prompt()` (ban, delete, stop, new profile, rename) are platform
    dialogs: pywebview labels their buttons from its own English table, so a
    Ukrainian question came with OK / Cancel underneath. The system menu is left
    alone on purpose — that one belongs to the OS language, not to the app."""
    return {
        "global.ok": i18n.t("dialog.ok"),
        "global.cancel": i18n.t("dialog.cancel"),
        "global.saveFile": i18n.t("dialog.save_file"),
    }


def app_knobs() -> dict:
    """What `Api` is constructed with. The declared knobs come through `tuning`, which
    clamps them and falls back on rubbish; `LLM_BATCH_SIZE` is deliberately not on the
    Settings screen, so it gets the same treatment from `config.env_num`. These were
    bare `int(...)` casts, which turned one typo in a hand-edited `.env` into an app
    that would not start at all."""
    k = tuning.read()
    return {"threshold": k["SCORE_THRESHOLD"], "x_days": k["X_FRESH_DAYS"],
            "feed_days": k["FEED_FRESH_DAYS"], "gh_days": k["GH_FRESH_DAYS"],
            "stagnant_days": k["TRACK_STAGNANT_DAYS"],
            "min_velocity": k["TREND_MIN_VELOCITY"],
            "batch_size": config.env_num("LLM_BATCH_SIZE", 120)}


def main():
    # every runtime path is anchored to the app, not the CWD (see topicparser/paths.py)
    store.DB_PATH = config.env_path("DB_PATH", "./topics.db")
    store.init_db()
    profiles_path = config.env_path("PROFILES_PATH", "./profiles.yaml")
    profiles = config.load_profiles(profiles_path)
    api = Api(profiles=profiles, build_collectors=build_collectors,
              build_client=build_client, **app_knobs(),
              # every knob below this line is resolved per run by `tuning`, not frozen
              # here — `off_interest` used to be parsed here and handed down, which
              # only added a lossy round-trip through a set
              profiles_path=profiles_path,
              prompt_loader=load_prompt, group_prompt_loader=load_group_prompt,
              dedup_prompt_loader=load_dedup_prompt,
              xgate_prompt_loader=load_xgate_prompt,
              feedgate_prompt_loader=load_feedgate_prompt,
              debug_dir=config.env_path("DEBUG_DIR", "./debug"),
              cookies_path=config.env_path("COOKIES_PATH", "./cookies.json"))
    # the UI ships INSIDE the bundle (read-only), unlike the files above
    # Size the window against the ACTUAL display; it was a hardcoded 1280x860 whatever
    # the screen. `webview.screens` answers before start(); if it will not, the helper
    # falls back to the minimum.
    # NO x/y ON PURPOSE — every backend centres the window only while both are absent
    # (cocoa `center()`, WinForms `CenterScreen`), and passing them is what made it open
    # off-centre a commit ago.
    try:
        screen = webview.screens[0]
        win_w, win_h = window_geometry(screen.width, screen.height)
    except Exception:
        win_w, win_h = window_geometry(0, 0)
    window = webview.create_window("Info Parser",
                          os.path.join(paths.bundle_dir(), "topicparser", "ui", "index.html"),
                          js_api=api, width=win_w, height=win_h, min_size=MIN_SIZE)

    def _confirm_quit_mac():
        # `closing` is a should_lock event fired SYNCHRONOUSLY on the main thread
        # (windowShouldClose_ / applicationShouldTerminate_), so NSAlert.runModal()
        # is driven DIRECTLY here, exactly like pywebview's own confirm_close. We
        # must NOT use window.create_confirmation_dialog on macOS: its cocoa
        # implementation does AppHelper.callAfter(...) + semaphore.acquire(), which
        # schedules work on the main run loop while blocking it => permanent
        # deadlock (the Cmd+Q beachball this once caused).
        import AppKit
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_(i18n.t("quit.title"))
        alert.setInformativeText_(i18n.t("quit.body"))
        alert.addButtonWithTitle_(i18n.t("quit.confirm"))       # first button
        alert.addButtonWithTitle_(i18n.t("quit.cancel"))  # second button
        alert.setAlertStyle_(AppKit.NSWarningAlertStyle)
        return alert.runModal() == AppKit.NSAlertFirstButtonReturn

    def _confirm_quit_windows():
        # The winforms backend has no such deadlock: create_confirmation_dialog is a
        # plain WinForms.MessageBox.Show on the calling thread, so the pywebview API
        # is safe here (OK = quit, Cancel = keep running).
        return window.create_confirmation_dialog(
            i18n.t("quit.title"), i18n.t("quit.body"))

    def on_closing():
        # Warn before closing/quitting mid-run (window X, Cmd+Q, Alt+F4).
        if not api.is_running():
            return True
        confirm = _confirm_quit_mac if platform.system() == "Darwin" else _confirm_quit_windows
        try:
            quit_chosen = confirm()
        except Exception:
            quit_chosen = True   # if the dialog can't show, don't trap the user in the app
        if quit_chosen:
            api.stop()           # wind the run down so Playwright closes + thread ends
            return True          # allow the close
        return False             # veto — keep the run going
    window.events.closing += on_closing

    webview.start(localization=build_localization())
    # window closed -> flush the WAL into topics.db + dispose the engine, so the
    # db file is self-contained (no data stranded in the -wal sidecar).
    store.close()

if __name__ == "__main__":
    main()
