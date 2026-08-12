from topicparser.collectors.x import parse_tweet

class FakeEl:
    """`inner` = the whole cell's inner_text (carries the reply/repost label);
    `text` = just the tweet body. They differ for replies."""
    def __init__(self, href, text, datetime_, inner=None):
        self._href, self._text, self._dt = href, text, datetime_
        self._inner = inner if inner is not None else text
    def links(self): return [self._href]
    def inner_text(self): return self._inner
    def tweet_text(self): return self._text
    def time_datetime(self): return self._dt

def test_parse_ok():
    el = FakeEl("/foo/status/123", "hello world", "2026-07-07T00:00:00Z")
    sig = parse_tweet(el, profile="Crypto")
    assert sig.source == "x" and sig.url == "https://x.com/foo/status/123"
    assert sig.title == "@foo" and "hello" in sig.description

def test_parse_skips_reply_english():
    el = FakeEl("/foo/status/123", "hi", "2026-07-07T00:00:00Z",
                inner="Replying to\n@bar\nhi")
    assert parse_tweet(el, profile="Crypto") is None

def test_parse_skips_reply_ukrainian():
    # X UI language is Ukrainian on this account -> label is "У відповідь", not
    # "Replying to". This is the real bug: Ukrainian replies slipped through.
    el = FakeEl("/foo/status/123", "hi", "2026-07-07T00:00:00Z",
                inner="У відповідь\n@bar\nhi")
    assert parse_tweet(el, profile="Crypto") is None
