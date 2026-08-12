"""One flaky source must not cost the whole collection.

Both collectors used to let a single failure escape the loop: one X account that
timed out on `page.goto` discarded every tweet already scraped from the earlier
URLs, and one GitHub topic returning 403 discarded every repo from the other
topics. Nine X URLs and six GitHub topics per profile make that a coin flip on
every run. Now a failing source is skipped and REPORTED (never swallowed silently)
while the rest of the collection survives.
"""
import pytest
from topicparser.collectors.github import GitHubCollector
from topicparser.collectors.x import XCollector, XSessionExpired
from topicparser.models import Signal


def xsig(url):
    # The author has to be the account the URL belongs to: a profile timeline can
    # only legitimately produce its own posts, and the collector now enforces that.
    handle = url.rsplit("/", 1)[-1].split("#")[0]
    return Signal.make(source="x", title=f"@{handle}", description="t", url=url,
                       date="", profile="AI")


class FlakySession:
    """Fails on the URL containing `bad`, returns one signal for the others."""
    def __init__(self, cookies_path, limit, max_scrolls):
        self.scraped = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def scrape(self, url, profile):
        if "bad" in url:
            raise RuntimeError("Timeout 30000ms exceeded")
        self.scraped.append(url)
        return [xsig(url + "#1")]


def test_x_collect_keeps_signals_from_the_urls_that_worked():
    warns = []
    c = XCollector(cookies_path="c.json", session_factory=FlakySession,
                   sleep=lambda s: None)
    c.warn = warns.append
    cfg = {"x": {"accounts": ["good1", "bad", "good2"], "lists": [], "searches": []}}
    out = c.collect("AI", cfg)
    assert sorted(s.url for s in out) == ["https://x.com/good1#1", "https://x.com/good2#1"]
    assert len(warns) == 1 and "bad" in warns[0]


def test_x_collect_still_propagates_session_expiry():
    # a dead cookie is NOT a per-URL problem — every remaining URL would fail the
    # same way, so it must still reach the user as the red "onovy cookies" banner.
    class ExpiredSession(FlakySession):
        def scrape(self, url, profile):
            raise XSessionExpired("сесія протермінована")

    c = XCollector(cookies_path="c.json", session_factory=ExpiredSession,
                   sleep=lambda s: None)
    cfg = {"x": {"accounts": ["a"], "lists": [], "searches": []}}
    with pytest.raises(XSessionExpired):
        c.collect("AI", cfg)


def test_session_reports_a_missing_cookies_file_instead_of_vanishing():
    # main.py used to simply not build the collector when cookies.json was absent,
    # so X disappeared from the run with no message at all. The check sits before
    # the browser launch, so this never touches Playwright.
    from topicparser.collectors.x import _PlaywrightSession
    s = _PlaywrightSession("./definitely-missing-cookies.json", limit=10, max_scrolls=5)
    with pytest.raises(XSessionExpired) as e:
        s.__enter__()
    assert "cookies" in str(e.value)


class FakeResponse:
    def __init__(self, items):
        self._items = items

    def raise_for_status(self):
        pass

    def json(self):
        return {"items": self._items}


def _repo(name):
    return {"full_name": name, "description": "d", "html_url": f"https://github.com/{name}",
            "pushed_at": "2026-07-30T00:00:00Z", "created_at": "2026-07-01T00:00:00Z",
            "stargazers_count": 10}


def test_github_collect_keeps_repos_from_the_topics_that_worked(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        if params["q"].startswith("topic:bad"):
            raise RuntimeError("403 secondary rate limit")
        return FakeResponse([_repo("owner/" + params["q"].split()[0].split(":")[1])])

    monkeypatch.setattr("topicparser.collectors.github.requests.get", fake_get)
    warns = []
    c = GitHubCollector(token="t")
    c.warn = warns.append
    out = c.collect("AI", {"github": {"topics": ["mcp", "bad", "llm"]}})
    assert sorted(s.title for s in out) == ["owner/llm", "owner/mcp"]
    assert len(warns) == 1 and "bad" in warns[0]


def test_a_repo_that_cannot_be_re_measured_reaches_the_warning_banner(monkeypatch):
    """`measure_tracked` printed to stderr, which a --windowed build has nowhere to
    put. A repo that stops answering shows a stale velocity and can never trend, so
    the miss belongs in the banner with every other collector failure."""
    from topicparser import store

    monkeypatch.setattr(store, "get_tracked_repos", lambda: ["owner/gone", "owner/fine"])
    measured = []
    monkeypatch.setattr(store, "record_stars", lambda r, s: measured.append((r, s)))

    def fake_get(url, headers=None, timeout=None):
        if "gone" in url:
            raise RuntimeError("404")
        return FakeStarResponse(42)

    class FakeStarResponse:
        def __init__(self, stars):
            self._stars = stars

        def raise_for_status(self):
            pass

        def json(self):
            return {"stargazers_count": self._stars}

    monkeypatch.setattr("topicparser.collectors.github.requests.get", fake_get)
    warns = []
    c = GitHubCollector(token="t")
    c.warn = warns.append
    c.measure_tracked()

    assert measured == [("owner/fine", 42)]          # the healthy repo still measured
    assert len(warns) == 1 and "owner/gone" in warns[0]
