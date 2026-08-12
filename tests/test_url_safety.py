"""A link reaching the UI is attacker-influenced (it comes off a scraped page), and
the UI runs inside pywebview with the whole `Api` exposed as window.pywebview.api.
So a `javascript:` URL that survives to an <a href> is not a cosmetic problem: one
click runs script with full access to the local API. Schemes are whitelisted at both
ends — where the link is built (x collector) and where it is opened (Api.open_url)."""
import pytest

from topicparser.api import Api
from topicparser.collectors.x import parse_tweet


def _api():
    return Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
               threshold=70, x_days=3, gh_days=60)


class FakeEl:
    def __init__(self, href):
        self._href = href
    def links(self):
        return [self._href]
    def inner_text(self):
        return "some tweet"
    def tweet_text(self):
        return "some tweet"
    def time_datetime(self):
        return "2026-08-06T10:00:00Z"
    def repost_href(self):
        return None


@pytest.mark.parametrize("url", [
    "javascript:alert(1)",
    "JavaScript:alert(1)",          # scheme match must be case-insensitive
    "data:text/html,<script>x</script>",
    "file:///etc/passwd",
    "vbscript:msgbox(1)",
    "",
    None,
])
def test_open_url_refuses_anything_but_http(url, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda u: opened.append(u))
    assert _api().open_url(url) is False
    assert opened == []


@pytest.mark.parametrize("url", ["https://github.com/a/b", "http://example.com/x"])
def test_open_url_allows_http_and_https(url, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", lambda u: opened.append(u))
    assert _api().open_url(url) is True
    assert opened == [url]


def test_scraped_tweet_href_with_a_script_scheme_is_dropped():
    # `/status/<id>` can appear inside a hostile scheme too — the old check only
    # looked for that substring, then used the href verbatim when it was absolute.
    assert parse_tweet(FakeEl("javascript:x/status/123"), "AI") is None


def test_scraped_tweet_href_off_x_is_dropped():
    assert parse_tweet(FakeEl("https://evil.example.com/u/status/123"), "AI") is None


def test_ordinary_relative_tweet_href_still_works():
    s = parse_tweet(FakeEl("/OpenAI/status/123"), "AI")
    assert s is not None and s.url == "https://x.com/OpenAI/status/123"


def test_absolute_x_tweet_href_still_works():
    s = parse_tweet(FakeEl("https://x.com/OpenAI/status/123"), "AI")
    assert s is not None and s.url == "https://x.com/OpenAI/status/123"
    # the author came out as "https:" — the split assumed a relative href
    assert s.title == "@OpenAI"
