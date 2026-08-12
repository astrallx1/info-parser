"""The 2026-08-22 review, batch B: the fixes that change what the SCORER SEES.

Separated from batch A on purpose. Each of these alters a signal's text, its length or
how many signals there are, so a run after this commit is not comparable with the three
rows already in the run table — and mixing them into A would have made it impossible to
say whether a score moved because of a new Atom description or because of something in
the safety batch.

Replay cannot measure this batch either: `replay.load_signals` reads `text` out of an
OLD debug log, where the empty descriptions are already baked in. One live run is part
of the work here, not a check after it.
"""
import os

import pytest

from topicparser.collectors import feeds
from topicparser.models import Signal
from topicparser.prefilter import drop_off_interest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --- 08 + 09: the description the model actually reads ------------------------------
@pytest.mark.parametrize("raw,want", [
    ("<p>Paragraph one.</p><p>Two.</p>", "Paragraph one. Two."),
    ("<p>Hello &amp; welcome</p>", "Hello & welcome"),
    # tags come off FIRST and the unescaping second. The other order turns escaped
    # prose into tags and then eats it: `_TAG` is `<[^>]+>`, which happily matches
    # "< 10 and x >" once the entities are open.
    ("5 &lt; 10 and x &gt; y", "5 < 10 and x > y"),
    ("Q&amp;A with the team", "Q&A with the team"),
    ("caf&#233; &nbsp;launch", "café launch"),
])
def test_entities_are_decoded_after_the_tags_come_off(raw, want):
    assert feeds._text(raw) == want


def test_an_atom_xhtml_summary_is_not_empty():
    # `el.text` is the text BEFORE the first child element, and an xhtml summary keeps
    # everything in children — so the signal reached the scorer with no text at all and
    # scored on its title alone.
    xml = b"""<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom"><entry>
      <title>Release</title><link href="https://lab.example/1"/>
      <updated>2026-08-20T10:00:00Z</updated>
      <summary type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml">
        <p>We shipped.</p></div></summary>
    </entry></feed>"""
    assert feeds.parse_feed(xml, "AI")[0].description == "We shipped."


def test_a_thumbnail_still_never_becomes_the_description():
    # DeepMind carries `<content medium="image" url="...">` on every item; reading it
    # as a summary shipped a thumbnail URL to the scorer as the signal's text.
    xml = b"""<?xml version="1.0"?><rss version="2.0"><channel><item>
      <title>Post</title><link>https://lab.example/2</link>
      <content medium="image" url="https://lab.example/thumb.png"/>
    </item></channel></rss>"""
    assert feeds.parse_feed(xml, "AI")[0].description == ""


# --- 11 + 12: the limits of the parse -----------------------------------------------
_BOMB = (b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaaaaaaaa">'
         b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
         b'<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">'
         b'<!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;">]>'
         b'<rss version="2.0"><channel><item><title>&d;</title>'
         b'<link>https://a.b/3</link><description>x</description></item></channel></rss>')


def test_an_entity_bomb_is_refused():
    assert feeds.parse_feed(_BOMB, "AI") == []


def test_an_ordinary_doctype_still_parses():
    # Rejecting `<!DOCTYPE` outright would break live feeds that carry one with no
    # entity declarations at all. The ENTITY declaration is the bomb, and the condition.
    xml = (b'<?xml version="1.0"?><!DOCTYPE rss PUBLIC "-//X//DTD" "http://x/rss.dtd">'
           b'<rss version="2.0"><channel><item><title>Fine</title>'
           b'<link>https://a.b/4</link></item></channel></rss>')
    assert [s.title for s in feeds.parse_feed(xml, "AI")] == ["Fine"]


def test_the_words_entity_in_a_title_are_not_a_bomb():
    xml = (b'<?xml version="1.0"?><rss version="2.0"><channel><item>'
           b'<title>On &lt;!ENTITY and other XML traps</title>'
           b'<link>https://a.b/5</link></item></channel></rss>')
    assert feeds.parse_feed(xml, "AI")


def test_a_feed_body_is_read_with_a_ceiling(monkeypatch):
    # `r.content` pulled the whole response into memory: a timeout bounds how long a
    # feed may take to answer, not how much it may send.
    class _R:
        status_code = 200

        def raise_for_status(self):
            pass

        def iter_content(self, n):
            for _ in range(200):
                yield b"x" * 65536          # 12.5 MB, over the ceiling

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(feeds.requests, "get", lambda *a, **kw: _R())
    col = feeds.FeedCollector()
    warns = []
    col.warn = warns.append
    assert col.collect("AI", {"feeds": {"urls": ["https://lab.example/rss"]}}) == []
    assert warns, "an oversized feed must be reported, not silently empty"


# --- 10: a title is not unbounded ---------------------------------------------------
def test_a_title_is_capped():
    # Measured at 100 000 characters out of a hostile feed — it rides into the scoring
    # payload (which is paid for by the token) and into the DB.
    s = Signal.make(source="feed", title="t" * 100_000, description="d",
                    url="u", date="", profile="AI")
    assert len(s.title) == 200


# --- 14: a term with a space matched prose and missed every repo name ---------------
def _sig(title="own/repo", desc=""):
    return Signal.make(source="github", title=title, description=desc,
                       url="https://github.com/own/repo", date="", profile="AI")


@pytest.mark.parametrize("title,term,dropped", [
    ("user/stable-diffusion-webui", "stable diffusion", True),      # was kept
    ("user/stablediffusion-ui", "stable diffusion", False),
    ("user/grok-cli", "grok", True),
    ("user/ai-grok-wrapper", "grok", True),
    ("user/grokking-algorithms", "grok", False),
    ("user/xgrok", "grok", False),
    ("user/agent-kit", "agent", True),
    ("user/agents-sdk", "agent", False),
    ("user/agentic-flow", "agent", False),
    ("user/c++-lib", "c++", True),
    # normalising both sides ALWAYS would collapse `c++` to `c` and start dropping
    # these two — which is why the phrase path only runs for a term with a space
    ("user/c-compiler", "c++", False),
    ("user/objective-c", "c++", False),
])
def test_off_interest_terms_match_the_same_way_in_a_repo_name(title, term, dropped):
    out = drop_off_interest([_sig(title=title)], {term})
    assert (out == []) is dropped, title


def test_a_multiword_term_still_matches_prose():
    assert drop_off_interest([_sig(desc="a stable diffusion tool")],
                             {"stable diffusion"}) == []
