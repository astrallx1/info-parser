from topicparser.collectors.x import parse_tweet

class FakeEl:
    """`inner` = the whole cell's inner_text (carries the reply/repost label);
    `text` = just the tweet body. They differ for replies.
    `repost` = the reposter's profile path, as the social-context block carries it."""
    def __init__(self, href, text, datetime_, inner=None, repost=None):
        self._href, self._text, self._dt = href, text, datetime_
        self._inner = inner if inner is not None else text
        self._repost = repost
    def links(self): return [self._href]
    def inner_text(self): return self._inner
    def tweet_text(self): return self._text
    def time_datetime(self): return self._dt
    def repost_href(self): return self._repost

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

def test_parse_skips_repost():
    # A list member reposting somebody: X renders the ORIGINAL tweet, so every link
    # in the cell belongs to the original author. The author was read off that link,
    # which is how people who are in NO selected source reached the feed and the .md.
    # Measured on one list: 6 of 14 visible entries were reposts.
    el = FakeEl("/stranger/status/123", "hi", "2026-07-07T00:00:00Z",
                inner="Curator reposted\nhi", repost="/curator")
    assert parse_tweet(el, profile="Crypto") is None

def test_parse_skips_self_repost():
    # The reposter IS the author (an account resurfacing its own older post). The
    # owner's call is to drop reposts entirely, so identity does not rescue it.
    el = FakeEl("/lab/status/123", "hi", "2026-07-07T00:00:00Z",
                repost="/lab")
    assert parse_tweet(el, profile="Crypto") is None

def test_parse_keeps_tweet_with_social_context_but_no_link():
    # "Pinned" is a social-context block too, and it carries no profile link. Keying
    # the drop on the LINK rather than on the label keeps pinned posts and stays out
    # of the translated-text trap REPLY_MARKERS already sits in.
    el = FakeEl("/foo/status/123", "hi", "2026-07-07T00:00:00Z",
                inner="Pinned\nhi", repost=None)
    assert parse_tweet(el, profile="Crypto") is not None
