"""X injects posts by people who are in no selected source, and marks them with nothing.

The repost guard closed one door: a repost renders as the ORIGINAL tweet, so its
author reached the feed. It works — measured on the owner's own list, 39 alien cells,
every one of them a repost, none scored. But two authors still got through
(`@lecturehall`, `@popsinger`), and driving the live page found their cells carry NO
marker at all: no `placementTracking`, no `socialContext`, the same testids as a
member's cell. There is nothing in the DOM to key on.

So the only thing that can decide is WHO the source is allowed to produce: the account
itself for an account URL, the membership for a list. Both are cheap and neither
depends on a label X can translate or remove.
"""
import pytest

from topicparser.collectors import x as xc
from topicparser.models import Signal


def _tweet(handle, i=0):
    return Signal.make(source="x", title=f"@{handle}", description="t",
                       url=f"https://x.com/{handle}/status/10000000{i}",
                       date="2026-08-30", profile="AI")


class TestSourceHandles:
    def test_an_account_url_may_only_produce_that_account(self):
        assert xc.source_handles("https://x.com/OpenAI") == {"openai"}

    def test_a_list_url_takes_the_membership(self):
        got = xc.source_handles("https://x.com/i/lists/123", members={"Foo", "bar"})
        assert got == {"foo", "bar"}

    def test_a_list_with_no_membership_read_constrains_nothing(self):
        # Fail OPEN. A members page that would not load must cost the run its
        # tweets, not its whole X collection.
        assert xc.source_handles("https://x.com/i/lists/123", members=None) is None
        assert xc.source_handles("https://x.com/i/lists/123", members=set()) is None

    def test_a_search_constrains_nothing(self):
        assert xc.source_handles("https://x.com/search?q=mcp&f=live") is None


class TestDropStrangers:
    def test_it_drops_an_author_the_source_cannot_produce(self):
        sigs = [_tweet("foo"), _tweet("popsinger"), _tweet("Bar")]
        kept = xc.drop_strangers(sigs, {"foo", "bar"})
        assert [s.title for s in kept] == ["@foo", "@Bar"]

    def test_matching_is_case_insensitive(self):
        # X handles are case-insensitive and the members page prints them however it
        # likes; a case mismatch would drop every real member.
        kept = xc.drop_strangers([_tweet("SomeFeedAcc")], {"somefeedacc"})
        assert len(kept) == 1

    def test_no_constraint_keeps_everything(self):
        sigs = [_tweet("a"), _tweet("b")]
        assert xc.drop_strangers(sigs, None) == sigs

    def test_a_signal_with_no_handle_survives(self):
        # Never let a parsing oddity silently eat a tweet.
        odd = Signal.make(source="x", title="", description="t",
                          url="https://x.com/x/status/1", date="", profile="AI")
        assert xc.drop_strangers([odd], {"someone"}) == [odd]


class TestMembersScrape:
    class _El:
        def __init__(self, href):
            self._href = href

        def get_attribute(self, _name):
            return self._href

    class _Page:
        """A members page that yields two handles and then stops growing."""
        def __init__(self, hrefs, url="https://x.com/i/lists/9/members"):
            self._hrefs, self.url = hrefs, url
            self.goto_calls = []

        def goto(self, url, **_kw):
            self.goto_calls.append(url)

        def query_selector_all(self, _sel):
            return [TestMembersScrape._El(h) for h in self._hrefs]

        def evaluate(self, *_a):
            pass

        def close(self):
            pass

    def test_it_reads_the_handles_off_the_member_cells(self):
        page = self._Page(["/foo", "/Bar", "/foo"])
        got = xc.read_members(page, "9", sleep=lambda *_a: None, max_scrolls=2)
        assert got == {"foo", "bar"}
        assert page.goto_calls[0].endswith("/i/lists/9/members")

    def test_a_login_redirect_on_the_members_page_is_not_a_dead_session(self):
        # This page is an extra, best-effort request. A redirect here must not raise
        # XSessionExpired and take the whole X collection with it — the timeline
        # itself is what decides that.
        page = self._Page(["/foo"], url="https://x.com/i/flow/login")
        assert xc.read_members(page, "9", sleep=lambda *_a: None, max_scrolls=1) is None

    def test_a_page_that_throws_returns_no_constraint(self):
        class Boom(self._Page):
            def query_selector_all(self, _sel):
                raise RuntimeError("nope")

        assert xc.read_members(Boom(["/x"]), "9", sleep=lambda *_a: None,
                               max_scrolls=1) is None

    def test_junk_paths_are_not_handles(self):
        page = self._Page(["/i/lists/9", "/home", "/foo", "/foo/status/1", "/"])
        assert xc.read_members(page, "9", sleep=lambda *_a: None, max_scrolls=1) == {"foo"}
