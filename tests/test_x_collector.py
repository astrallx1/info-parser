import random
from topicparser.collectors.x import build_urls, XCollector
from topicparser.models import Signal


def sig(url):
    return Signal.make(source="x", title="@a", description="t", url=url,
                       date="", profile="AI")


def test_build_urls_order_accounts_lists_searches():
    cfg = {"accounts": ["OpenAI", "@AnthropicAI"], "lists": ["123"],
           "searches": ["ai agents"]}
    assert build_urls(cfg) == [
        "https://x.com/OpenAI",
        "https://x.com/AnthropicAI",
        "https://x.com/i/lists/123",
        "https://x.com/search?q=ai%20agents&f=live",   # query URL-encoded
    ]


def test_build_urls_empty():
    assert build_urls({"accounts": [], "lists": [], "searches": []}) == []


def test_build_urls_encodes_search_special_chars():
    # a raw space/&/# in a search query would otherwise break the URL
    cfg = {"accounts": [], "lists": [], "searches": ["a&b c"]}
    assert build_urls(cfg) == ["https://x.com/search?q=a%26b%20c&f=live"]


def test_build_urls_lists_accept_objects_and_strings():
    # a list entry may be a bare id (legacy) or a {id, name} object (named lists)
    cfg = {"accounts": [], "searches": [],
           "lists": [{"id": "123", "name": "Weekly reads"}, "456"]}
    assert build_urls(cfg) == ["https://x.com/i/lists/123", "https://x.com/i/lists/456"]


class FakeSession:
    """Records construction + scrape calls; returns one signal per url."""
    instances = []

    def __init__(self, cookies_path, limit, max_scrolls):
        self.cookies_path, self.limit, self.max_scrolls = cookies_path, limit, max_scrolls
        self.scraped = []
        self.closed = False
        FakeSession.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.closed = True

    def scrape(self, url, profile):
        self.scraped.append(url)
        return [sig(url + "#1")]


def make_collector(**kw):
    FakeSession.instances = []
    return XCollector(cookies_path="c.json", session_factory=FakeSession, **kw)


def test_collect_opens_exactly_one_session_for_many_urls():
    c = make_collector(sleep=lambda s: None)
    cfg = {"x": {"accounts": ["a", "b"], "lists": ["9"], "searches": []}}
    c.collect("AI", cfg)
    assert len(FakeSession.instances) == 1
    assert FakeSession.instances[0].scraped == [
        "https://x.com/a", "https://x.com/b", "https://x.com/i/lists/9"]
    assert FakeSession.instances[0].closed is True


def test_collect_dedups_signals_by_url():
    class DupSession(FakeSession):
        def scrape(self, url, profile):
            return [sig("https://x.com/same/status/1")]
    FakeSession.instances = []
    c = XCollector(cookies_path="c.json", session_factory=DupSession,
                   sleep=lambda s: None)
    cfg = {"x": {"accounts": ["a", "b"], "lists": [], "searches": []}}
    out = c.collect("AI", cfg)
    assert len(out) == 1


def test_collect_paces_between_urls_with_delay_in_range():
    slept = []
    c = make_collector(sleep=lambda s: slept.append(s), rng=random.Random(0),
                       min_delay=3.0, max_delay=8.0)
    cfg = {"x": {"accounts": ["a", "b", "c"], "lists": [], "searches": []}}
    c.collect("AI", cfg)
    # 3 urls -> 2 inter-url delays (no delay before the first)
    assert len(slept) == 2
    assert all(3.0 <= s <= 8.0 for s in slept)


def test_collect_stops_early_when_cancel_event_set():
    import threading
    event = threading.Event()

    class TripSession(FakeSession):
        def scrape(self, url, profile):
            self.scraped.append(url)
            if url.endswith("/a"):
                event.set()               # user hits Stop after the first URL
            return [sig(url + "#1")]

    FakeSession.instances = []
    c = XCollector(cookies_path="c.json", session_factory=TripSession, sleep=lambda s: None)
    c.cancel_event = event
    cfg = {"x": {"accounts": ["a", "b", "c"], "lists": [], "searches": []}}
    out = c.collect("AI", cfg)
    assert FakeSession.instances[0].scraped == ["https://x.com/a"]   # b, c never scraped
    assert len(out) == 1


def test_collect_no_x_config_returns_empty():
    c = make_collector(sleep=lambda s: None)
    assert c.collect("AI", {}) == []
    assert len(FakeSession.instances) == 0


def test_collect_propagates_session_expiry():
    # an expired X session must NOT be a silent empty result — it propagates so the
    # pipeline surfaces a red warning banner (not just a stderr line the user won't see)
    import pytest
    from topicparser.collectors.x import XSessionExpired

    class ExpiredSession(FakeSession):
        def scrape(self, url, profile):
            raise XSessionExpired("сесія протермінована")

    FakeSession.instances = []
    c = XCollector(cookies_path="c.json", session_factory=ExpiredSession, sleep=lambda s: None)
    cfg = {"x": {"accounts": ["a"], "lists": [], "searches": []}}
    with pytest.raises(XSessionExpired):
        c.collect("AI", cfg)


def test_scrape_raises_when_redirected_to_login():
    import pytest
    from topicparser.collectors.x import _PlaywrightSession, XSessionExpired

    class LoginPage:
        # X redirects an expired session to /login instead of the feed
        def __init__(self): self.url = "https://x.com/login"
        def goto(self, *a, **k): pass
        def query_selector_all(self, sel): return []
        def evaluate(self, js): pass
        def close(self): pass

    class FakeCtx:
        def new_page(self): return LoginPage()

    s = _PlaywrightSession("c.json", limit=10, max_scrolls=5, sleep=lambda _: None)
    s.ctx = FakeCtx()
    with pytest.raises(XSessionExpired):
        s.scrape("https://x.com/i/lists/1", "AI")


def test_scrape_stops_scrolling_when_cancel_set():
    # Stop pressed mid-scrape -> the scroll loop bails within one iteration,
    # not after all max_scrolls (~2 min of scrolling)
    import threading
    from topicparser.collectors.x import _PlaywrightSession
    ev = threading.Event()
    n = {"sleeps": 0}
    def fake_sleep(_):
        n["sleeps"] += 1
        if n["sleeps"] >= 2:   # dwell = 1st sleep, first scroll's pause = 2nd
            ev.set()
    class FakePage:
        def __init__(self): self.url = "https://x.com/list"; self.scrolls = 0
        def goto(self, *a, **k): pass
        def query_selector_all(self, sel): return []
        def evaluate(self, js): self.scrolls += 1
        def close(self): pass
    page = FakePage()
    class FakeCtx:
        def new_page(self): return page
    s = _PlaywrightSession("c.json", limit=100, max_scrolls=40, sleep=fake_sleep)
    s.ctx = FakeCtx()
    s.cancel_event = ev
    s.scrape("https://x.com/list", "AI")
    assert page.scrolls == 1   # one scroll happened, then Stop broke the loop


# --- a dead session must not be written back over a live cookie file ---------------


def test_the_session_is_not_saved_when_it_expired(tmp_path):
    """`__exit__` wrote `storage_state` unconditionally, including on the way out of an
    XSessionExpired — so the redirected-to-login state was persisted over the file, and
    a cookie jar that might still have been usable was replaced by a dead one."""
    from topicparser.collectors.x import _PlaywrightSession, XSessionExpired

    saved = []

    class Ctx:
        def storage_state(self, path):
            saved.append(path)

    s = _PlaywrightSession.__new__(_PlaywrightSession)
    s.ctx, s.browser, s._pw = Ctx(), None, None
    s.cookies_path = str(tmp_path / "cookies.json")

    s.__exit__(XSessionExpired, XSessionExpired("dead"), None)
    assert saved == [], "a dead session overwrote the cookie file"

    s.__exit__(None, None, None)
    assert saved == [s.cookies_path], "a healthy session still refreshes it"
