import os, platform, random, re, sys, time
from typing import Optional
from urllib.parse import quote, urlparse
from topicparser import paths
from topicparser.models import Signal
from topicparser.collectors.stealth import apply_stealth
from topicparser import i18n


class XSessionExpired(Exception):
    """Raised when X redirects to /login (cookies dead). Propagated so the pipeline
    surfaces a visible warning instead of silently returning zero tweets."""

# Real desktop Chrome UA (headless otherwise reports "HeadlessChrome").
_CHROME = "149.0.0.0"           # one place, or the strings below drift apart
_UA_OS = {"Windows": "Windows NT 10.0; Win64; x64",
          "Darwin": "Macintosh; Intel Mac OS X 10_15_7",
          "Linux": "X11; Linux x86_64"}


def real_ua(system: str | None = None) -> str:
    """The UA for the machine this actually runs on.

    It used to be hardcoded to macOS, so on Windows the browser announced
    "Macintosh" while the page's own `navigator.platform` answered "Win32". No real
    browser contradicts itself that way, which made the one string meant to look
    ordinary into the tell — and `stealth.py` patches `webdriver`, plugins, languages
    and WebGL but NOT `platform`, so nothing covered for it. Making the claim TRUE is
    the fix; spoofing `platform` to match a lie would just be one more surface.
    An unrecognised system falls back to Linux rather than raising: a missing UA is
    louder than a wrong one."""
    os_part = _UA_OS.get(system or platform.system(), _UA_OS["Linux"])
    return (f"Mozilla/5.0 ({os_part}) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{_CHROME} Safari/537.36")

# Reply-context label, one per X UI language. This is the language of the SCRAPING
# ACCOUNT's X interface, NOT the app's — do not "clean it up" when translating the
# app, or replies leak back in as signals for anyone whose X is not in English.
# No stable data-testid exists on this block, so we match text; add a phrase here
# for each UI language a user might have.
REPLY_MARKERS = ("Replying to", "У відповідь")

def _tweet_id(href: str) -> Optional[str]:
    m = re.search(r"/status/(\d+)", href)
    return m.group(1) if m else None


# A tweet href must be a relative path on the page, or an absolute one ON x.com.
# Anything else is not a tweet link: the old check merely looked for `/status/<id>`
# ANYWHERE in the string, so `javascript:x/status/1` matched and was then used
# verbatim as the card's href — a scripted link one click away from the whole
# `Api` surface that pywebview exposes to the page.
_TWEET_HREF = re.compile(r"(?:/|https://(?:x|twitter)\.com/)[^\s]*/status/\d+$", re.I)

def parse_tweet(el, profile: str) -> Optional[Signal]:
    """Pure parse: `el` exposes links()/inner_text()/tweet_text()/time_datetime()."""
    href = next((h for h in el.links() if _TWEET_HREF.match(h or "")), None)
    if not href or not _tweet_id(href):
        return None
    inner = el.inner_text()
    if any(m in inner for m in REPLY_MARKERS):
        return None
    # the handle is the path segment before /status/ — read it from the match so an
    # absolute href doesn't yield "https:" the way splitting the raw string did
    author = re.search(r"/([^/]+)/status/\d+$", href).group(1)
    text = el.tweet_text() or ""
    if not text:
        return None
    url = f"https://x.com{href}" if href.startswith("/") else href
    return Signal.make(source="x", title=f"@{author}", description=text,
                       url=url, date=el.time_datetime() or "", profile=profile)

def _list_id(entry) -> str:
    """A list entry is either a bare id string or a {id, name} object."""
    return entry["id"] if isinstance(entry, dict) else entry

def build_urls(x_cfg: dict) -> list[str]:
    """X profile config -> ordered scrape URLs (accounts, then lists, then searches)."""
    return [f"https://x.com/{a.lstrip('@')}" for a in x_cfg.get("accounts", [])] \
         + [f"https://x.com/i/lists/{_list_id(l)}" for l in x_cfg.get("lists", [])] \
         + [f"https://x.com/search?q={quote(q)}&f=live" for q in x_cfg.get("searches", [])]

# --- Playwright driver (adapts real elements to the parse interface) ---
class _ElAdapter:
    def __init__(self, el): self._el = el
    def links(self):
        return [a.get_attribute("href") or "" for a in
                self._el.query_selector_all("a[href*='/status/']")]
    def inner_text(self): return self._el.inner_text()
    def tweet_text(self):
        t = self._el.query_selector("[data-testid='tweetText']")
        return t.inner_text() if t else ""
    def time_datetime(self):
        t = self._el.query_selector("time[datetime]")
        return t.get_attribute("datetime") if t else None


def _browser_cache_dir() -> str:
    """Where `playwright install` puts browsers when nobody overrides it."""
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    elif sys.platform == "darwin":
        base = os.path.join(home, "Library", "Caches")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")
    return os.path.join(base, "ms-playwright")


def use_installed_browsers() -> None:
    """Point a FROZEN build at the machine's Chromium instead of at its own bundle.

    playwright's `_transport.connect` forces `PLAYWRIGHT_BROWSERS_PATH=0` whenever
    `sys.frozen` is set, and "0" means "browsers ship inside the package". We do not
    bundle them (~150 MB, and version-locked to the build), so the packaged app went
    looking inside `Info Parser.app/.../driver/package/.local-browsers` and every X
    collection died. It uses `setdefault`, so setting the variable first wins.

    Only touched when frozen: from source playwright already resolves to this exact
    directory, and an explicit setting is always left alone."""
    if not paths.is_frozen() or os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        return
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = _browser_cache_dir()


def is_login_url(url: str) -> bool:
    """Did X bounce us to the login page?

    Matched as a substring of the whole URL, which reads a redirect into ordinary
    traffic: `@loginhelper` is a real handle and "openai login" is a legal search, and
    either one raised XSessionExpired — deliberately uncaught in `collect`, so ONE such
    source killed the entire X collection and reported a dead cookie jar. Only the PATH
    decides, and only the two paths X actually redirects to."""
    path = urlparse(url or "").path.rstrip("/").lower()
    return path in ("/login", "/i/flow/login")


class _PlaywrightSession:
    """One browser+context per profile (`collect` opens it, so a two-profile run
    opens two — sharing it across the whole run would need a lifecycle the collector
    does not own). Stealth applied once; each URL
    scraped in a new page within the SAME context so X sees one continuous session
    instead of a fresh 'device' per URL."""
    def __init__(self, cookies_path, limit, max_scrolls, headless=True,
                 sleep=time.sleep, rng=None):
        self.cookies_path, self.limit, self.max_scrolls = cookies_path, limit, max_scrolls
        self.headless, self.sleep = headless, sleep
        self.rng = rng or random.Random()
        self._pw = self.browser = self.ctx = None

    def __enter__(self):
        # Checked before the browser starts: without a cookie file X is simply not
        # reachable. main.py used to skip building the collector entirely in this
        # case, so X vanished from the run with no message and a cookie-less setup
        # just looked like a quiet news day.
        if not os.path.exists(self.cookies_path):
            raise XSessionExpired(
                i18n.t("error.cookies_missing", path=self.cookies_path))
        use_installed_browsers()          # must precede the driver spawn
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=self.headless)
        self.ctx = self.browser.new_context(
            storage_state=self.cookies_path, user_agent=real_ua(),
            viewport={"width": 1280, "height": 800}, locale="en-US")
        apply_stealth(self.ctx)
        return self

    def __exit__(self, exc_type=None, *a):
        # Refresh the cookie jar on the way out — X rotates tokens, and a session that
        # is never written back goes stale on its own. NOT when the session died: a
        # login redirect means the browser is holding the logged-OUT state, and saving
        # that overwrites a file that may still have had life in it. Only
        # XSessionExpired is treated this way; a per-URL failure is caught inside
        # `collect` and never reaches here.
        try:
            if self.ctx and exc_type is not XSessionExpired:
                self.ctx.storage_state(path=self.cookies_path)
        except Exception:
            pass
        if self.browser:
            self.browser.close()
        if self._pw:
            self._pw.stop()

    def scrape(self, url: str, profile: str) -> list[Signal]:
        page = self.ctx.new_page()
        found: dict[str, Signal] = {}
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            self.sleep(self.rng.uniform(4.0, 7.0))  # human dwell after load
            if is_login_url(page.url):
                raise XSessionExpired(
                    i18n.t("error.x_session_expired"))
            cancel = getattr(self, "cancel_event", None)
            scrolls = 0
            while len(found) < self.limit and scrolls < self.max_scrolls:
                if cancel is not None and cancel.is_set():   # Stop hit mid-scroll
                    break
                for el in page.query_selector_all("[data-testid='tweet']"):
                    try:
                        sig = parse_tweet(_ElAdapter(el), profile)
                        if sig:
                            found[sig.url] = sig
                    except Exception:
                        pass
                # gentle stepped scroll + jittered pause, not an instant jump-to-bottom
                page.evaluate("window.scrollBy(0, Math.round(window.innerHeight * 0.85))")
                self.sleep(self.rng.uniform(1.0, 2.5))
                scrolls += 1
            # which of the two caps ended the loop is the whole question behind
            # X_MAX_TWEETS: raising the tweet cap widens the net only while the scroll
            # ceiling is not the thing binding. The collector copies this into the run's
            # debug log per URL.
            self.last_scrolls = scrolls
        finally:
            page.close()
        return list(found.values())


class XCollector:
    source = "x"

    # `main` always passes these explicitly, so the defaults below are for tests and
    # for anything constructing the collector directly — which is exactly why they must
    # not disagree with `.env.example`. They are the THIRD copy of each number
    # (`.env.example`, `main`'s env_num fallback, here) and a test pins all three.
    def __init__(self, cookies_path: str, limit: int = 150, max_scrolls: int = 80,
                 min_delay: float = 3.0, max_delay: float = 8.0,
                 session_factory=_PlaywrightSession, sleep=time.sleep, rng=None):
        self.cookies_path, self.limit, self.max_scrolls = cookies_path, limit, max_scrolls
        self.min_delay, self.max_delay = min_delay, max_delay
        self.session_factory, self.sleep = session_factory, sleep
        self.rng = rng or random.Random()

    def collect(self, profile_name: str, profile_cfg: dict) -> list[Signal]:
        # FIRST line, before either early return: one collector instance serves every
        # profile in a run and `pipeline` reads this per profile, so a profile with no
        # X sources would otherwise report the previous profile's URLs as its own.
        self.stats = []            # per URL: what it returned, and what it cost
        x = profile_cfg.get("x")
        if not x:
            return []
        urls = build_urls(x)
        if not urls:
            return []
        out: dict[str, Signal] = {}
        cancel = getattr(self, "cancel_event", None)
        warn = getattr(self, "warn", None)
        with self.session_factory(self.cookies_path, self.limit, self.max_scrolls) as session:
            session.cancel_event = cancel   # so scrape's scroll loop can bail on Stop
            for i, u in enumerate(urls):
                if cancel is not None and cancel.is_set():   # Stop hit — abandon remaining URLs
                    break
                if i:  # human pause between sources (not before the first)
                    delay = self.rng.uniform(self.min_delay, self.max_delay)
                    if cancel is not None:
                        if cancel.wait(delay):   # interruptible pause; True => Stop during it
                            break
                    else:
                        self.sleep(delay)
                # One flaky URL (a `goto` timeout, a page X won't render) must not
                # discard the tweets already scraped from the earlier URLs — that is
                # most of a 15-minute run. Skip it, report it, keep going.
                # XSessionExpired is deliberately NOT caught: a dead cookie would fail
                # every remaining URL the same way, so it belongs at the top.
                try:
                    scraped = session.scrape(u, profile_name)
                except XSessionExpired:
                    raise
                except Exception as e:
                    if warn is not None:
                        warn(i18n.t("warn.x_url_skipped", url=u, error=e))
                    continue
                # What this URL cost and what it returned. `scrolls == max` cannot by
                # itself prove the scroll ceiling was binding (there is no
                # timeline-exhausted exit), so only the tweet COUNT separates a pinched
                # net from scrolling into the void — which is why both are recorded.
                self.stats.append({"url": u, "tweets": len(scraped),
                                   "scrolls": getattr(session, "last_scrolls", None)})
                for sig in scraped:
                    out[sig.url] = sig
        return list(out.values())
