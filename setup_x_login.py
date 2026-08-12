import os
import sys
import time

from playwright.sync_api import sync_playwright

from import_cookies import write_state, x_only
from topicparser import config

# This script opens the user's REAL Chrome profile, so the context holds every cookie
# that profile has — mail, banking, anything logged in. `storage_state()` dumps all of
# them, and this file used to write that dump verbatim, with default permissions.
# `write_state` filters to X and chmods 0600; the filter is shared with the other
# door (import_cookies) so a later fix cannot land on one of them only.


def chrome_user_data_dir() -> str:
    if sys.platform.startswith("win"):
        return os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Google/Chrome")
    return os.path.expanduser("~/.config/google-chrome")


def main():
    # anchored to the app, never to the CWD — see topicparser/paths.py
    cookies = config.env_path("COOKIES_PATH", "./cookies.json")
    print("Close Chrome fully first. Opening Chrome profile…")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=chrome_user_data_dir(), channel="chrome", headless=False)
        (ctx.pages[0] if ctx.pages else ctx.new_page()).goto("https://x.com/home")
        print("Log into X if needed. Saving cookies in 15s…")
        time.sleep(15)
        state = ctx.storage_state()
        ctx.close()
    write_state(state, cookies)
    print(f"Saved {len(x_only(state)['cookies'])} X cookies to {cookies}")


if __name__ == "__main__":
    main()
