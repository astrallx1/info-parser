#!/usr/bin/env python
"""Every closed finding of the 2026-08-22 review, re-proved in about a second.

The suite says the code does what its tests say. THIS says the specific bugs that were
found by hand are still dead — one check per finding, each reproducing the failure
rather than the fix, so a rewrite that happens to keep the tests green still trips here.

    .venv/bin/python tools/audit.py        # exit 0 = everything closed

No network, no keys, no browser. **A new bug gets a fix AND a check here**, or the next
rewrite quietly reopens it.
"""
import contextlib
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("APP_LANG", "en")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKS = []


def check(finding, what):
    def wrap(fn):
        CHECKS.append((finding, what, fn))
        return fn
    return wrap


@contextlib.contextmanager
def tmpdir():
    """A scratch folder that survives Windows.

    `TemporaryDirectory` deletes on exit and RAISES when a file is still open — and
    SQLite keeps the database open until the engine is disposed, so on Windows every
    check that touched a DB failed in its teardown while the check itself had passed.
    (POSIX does not care, which is exactly why CI runs on both.)"""
    d = tempfile.mkdtemp()
    try:
        yield d
    finally:
        with contextlib.suppress(Exception):
            from topicparser import store
            store.close()
        shutil.rmtree(d, ignore_errors=True)


def src(*parts):
    return open(os.path.join(ROOT, *parts), encoding="utf-8").read()


# --- 01 -----------------------------------------------------------------------------
@check("01", "a reply shape nobody met cannot kill a run")
def _parsers():
    from topicparser import ranker
    for raw in ['{"drop": null}', '{"drop": 3}', '{"drop": "1,2"}', '{"drop": {"a": 1}}',
                "{}", "[]", "not json", None]:
        assert ranker.parse_dedup(raw) == set(), raw
        assert ranker.parse_xgate(raw) == set(), raw
    for raw in ['{"groups": null}', '{"groups": ["x"]}', '{"groups": [{"indices": null}]}',
                '{"stale": null}', '{"groups": [{}]}', "not json", None]:
        out = ranker.parse_groups(raw)
        assert isinstance(out["groups"], list) and isinstance(out["stale"], list), raw
    for raw in ['{"scored": null}', '{"scored": [{"i": null}]}', '{"scored": "x"}', None]:
        assert ranker.parse_scored(raw) == [], raw

    class _None:                      # the client's own failure mode: content = None
        def make(self, messages):
            return None
    topics = [{"title": "T", "why": "w", "score": 80, "links": ["u"]}]
    assert ranker.dedup_shown(topics, ["shown"], _None()) == topics
    assert ranker.gate_tweets([], _None()) == set()


@check("01", "a dying run still writes its debug log")
def _debug_on_crash():
    from topicparser import pipeline
    with tmpdir() as d:
        # the stubs are module-level, so they MUST be put back: leaving
        # `get_banned_repos` returning an empty set made the ban check below pass an
        # unbanned repo and fail for a reason that had nothing to do with bans
        saved = _stub_store(pipeline.store)
        pipeline._collect_and_score, real = _boom, pipeline._collect_and_score
        try:
            pipeline.run(selected={"AI": {}}, profiles={"AI": {}}, collectors=[],
                         client=None, threshold=70, x_days=3, gh_days=60, debug_dir=d)
        except RuntimeError:
            pass
        finally:
            pipeline._collect_and_score = real
            for name, fn in saved.items():
                setattr(pipeline.store, name, fn)
        assert [f for f in os.listdir(d) if f.startswith("run-")], "no log for a dead run"


def _boom(*a, **kw):
    raise RuntimeError("parser died")


def _stub_store(store_mod):
    """Silence the DB calls a run makes before its profile loop. Returns the originals —
    the caller has to put them back, or the next check runs against these."""
    names = ("cleanup_topics", "prune_star_history", "drop_stagnant_repos",
             "detect_trending", "seen_links", "get_banned_repos", "get_recent_topics")
    saved = {n: getattr(store_mod, n) for n in names}
    for name in ("cleanup_topics", "prune_star_history", "drop_stagnant_repos"):
        setattr(store_mod, name, lambda *a, **kw: None)
    store_mod.detect_trending = lambda **kw: []
    store_mod.seen_links = lambda **kw: set()
    store_mod.get_banned_repos = lambda: set()
    store_mod.get_recent_topics = lambda **kw: []
    return saved


# --- 02 -----------------------------------------------------------------------------
@check("02", "only a real login PAGE reads as an expired session")
def _login():
    from topicparser.collectors.x import is_login_url
    for url, expired in [("https://x.com/loginhelper", False),
                         ("https://x.com/search?q=openai%20login", False),
                         ("https://x.com/i/flow/login", True),
                         ("https://x.com/login", True),
                         ("https://twitter.com/login?redirect_after_login=%2Fhome", True)]:
        assert is_login_url(url) is expired, url


# --- 03 -----------------------------------------------------------------------------
@check("03", "a mixed cluster leads with the member its badge came from")
def _cluster_link():
    from topicparser import ranker
    from topicparser.models import Signal
    tw = Signal.make(source="x", title="@dev", description="look", date="", profile="AI",
                     url="https://x.com/dev/status/999")
    gh = Signal.make(source="github", title="own/repo", description="repo", date="",
                     profile="AI", url="https://github.com/own/repo", stars=1200)
    t = ranker._assemble_topics(
        [tw, gh], [80, 75], ["t", "g"], ["r", "r"],
        {"groups": [{"indices": [0, 1], "title": "One story", "why": "w"}], "stale": []})[0]
    assert t["source"] == "gh" and t["links"][0] == "https://github.com/own/repo"


# --- 05 + 37 ------------------------------------------------------------------------
@check("05/37", "a key in the environment counts; an absent one still blocks")
def _keys():
    from topicparser import api as api_mod
    with tmpdir() as d:
        api_mod.paths.app_dir = lambda: d
        api = api_mod.Api(profiles={"profiles": {}}, build_collectors=lambda: [],
                          build_client=lambda: None, threshold=70, x_days=3, gh_days=60,
                          profiles_path=os.path.join(d, "p.yaml"),
                          cookies_path=os.path.join(d, "c.json"))
        keep = {k: os.environ.get(k) for k in ("GITHUB_TOKEN", "OPENAI_API_KEY")}
        try:
            os.environ["GITHUB_TOKEN"] = os.environ["OPENAI_API_KEY"] = "from-env"
            assert api.setup_state()["needs_onboarding"] is False
            for k in keep:
                os.environ.pop(k, None)
            assert api.setup_state()["needs_onboarding"] is True, "absent must still block"
        finally:
            for k, v in keep.items():
                if v is not None:
                    os.environ[k] = v


# --- 15 -----------------------------------------------------------------------------
@check("15", "a newline in a text knob cannot write a second .env line")
def _knob_newline():
    from topicparser import settings, tuning
    assert tuning.validate({"OFF_INTEREST": "crypto\nGITHUB_TOKEN=hijacked"})
    assert tuning.validate({"OFF_INTEREST": "crypto, agents"}) == []
    with tmpdir() as d:                 # and the writer's own half
        p = os.path.join(d, ".env")
        open(p, "w").write("GITHUB_TOKEN=real\nOFF_INTEREST=x\n")
        settings.write_env(p, {"OFF_INTEREST": "crypto"})
        assert settings.read_env(p)["GITHUB_TOKEN"] == "real"


# --- 16 -----------------------------------------------------------------------------
@check("16", "a ban written before the lowercase fix still matches and still lifts")
def _ban_case():
    from topicparser import prefilter, store
    from topicparser.models import Signal
    with tmpdir() as d:
        store.DB_PATH = os.path.join(d, "t.db")
        store.init_db()
        store.ban_repo("OpenAI/Whisper")                     # a pre-fix row, as typed
        sig = Signal.make(source="github", title="openai/whisper", description="",
                          url="https://github.com/openai/whisper", date="", profile="AI")
        assert prefilter.drop_banned([sig], store.get_banned_repos()) == []
        store.unban_repo("openai/whisper")
        assert store.get_banned_repos() == set(), "an old ban must still be liftable"


# --- 17 -----------------------------------------------------------------------------
@check("17", "each wipe keeps its own backup")
def _backups():
    from topicparser import store
    with tmpdir() as d:
        store.DB_PATH = os.path.join(d, "t.db")
        store.init_db()
        first, second = store.reset_all(topics=True), store.reset_all(topics=True)
        assert first != second and os.path.exists(first) and os.path.exists(second)


# --- 35 -----------------------------------------------------------------------------
@check("35", "the freshness filter and the cleanup answer the feed window the same way")
def _feed_window():
    assert "x_days if feed_days is None else feed_days" in src("topicparser", "prefilter.py")
    st = src("topicparser", "store.py")
    i = st.index("def cleanup_topics")
    assert "else x_days" in st[i:i + 900], "cleanup still defaults the feed to gh_days"


# --- 08 + 09 ------------------------------------------------------------------------
@check("08/09", "the description the model reads: tags off first, entities after")
def _feed_text():
    from topicparser.collectors import feeds
    for raw, want in [("<p>Paragraph one.</p><p>Two.</p>", "Paragraph one. Two."),
                      ("<p>Hello &amp; welcome</p>", "Hello & welcome"),
                      ("5 &lt; 10 and x &gt; y", "5 < 10 and x > y"),
                      ("Q&amp;A with the team", "Q&A with the team"),
                      ("caf&#233; &nbsp;launch", "café launch")]:
        assert feeds._text(raw) == want, raw
    atom = (b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry>'
            b'<title>R</title><link href="https://l/1"/><updated>2026-08-20T10:00:00Z</updated>'
            b'<summary type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml">'
            b'<p>We shipped.</p></div></summary></entry></feed>')
    assert feeds.parse_feed(atom, "AI")[0].description == "We shipped."
    thumb = (b'<?xml version="1.0"?><rss version="2.0"><channel><item><title>P</title>'
             b'<link>https://l/2</link><content medium="image" url="https://l/t.png"/>'
             b'</item></channel></rss>')
    assert feeds.parse_feed(thumb, "AI")[0].description == ""


# --- 11 + 12 ------------------------------------------------------------------------
@check("11/12", "an entity bomb is refused, an ordinary DOCTYPE is not")
def _feed_limits():
    from topicparser.collectors import feeds
    bomb = (b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaaaaaaaa">'
            b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
            b'<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">'
            b'<!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;">]>'
            b'<rss version="2.0"><channel><item><title>&d;</title>'
            b'<link>https://a.b/3</link></item></channel></rss>')
    assert feeds.parse_feed(bomb, "AI") == []
    plain = (b'<?xml version="1.0"?><!DOCTYPE rss PUBLIC "-//X//DTD" "http://x/rss.dtd">'
             b'<rss version="2.0"><channel><item><title>Fine</title>'
             b'<link>https://a.b/4</link></item></channel></rss>')
    assert [s.title for s in feeds.parse_feed(plain, "AI")] == ["Fine"]
    quoted = (b'<?xml version="1.0"?><rss version="2.0"><channel><item>'
              b'<title>On &lt;!ENTITY and other traps</title>'
              b'<link>https://a.b/5</link></item></channel></rss>')
    assert feeds.parse_feed(quoted, "AI"), "the WORD ENTITY in a title is not a bomb"
    assert feeds.MAX_FEED_BYTES <= 10 * 1024 * 1024


# --- 10 -----------------------------------------------------------------------------
@check("10", "a title is capped before it reaches a paid payload")
def _title_cap():
    from topicparser.models import Signal
    s = Signal.make(source="feed", title="t" * 100_000, description="d" * 100_000,
                    url="u", date="", profile="AI")
    assert len(s.title) == 200 and len(s.description) == 500


# --- 14 -----------------------------------------------------------------------------
@check("14", "an off-interest term matches a repo NAME as well as prose")
def _off_interest():
    from topicparser.models import Signal
    from topicparser.prefilter import drop_off_interest

    def sig(title="own/repo", desc=""):
        return Signal.make(source="github", title=title, description=desc, date="",
                           url="https://github.com/own/repo", profile="AI")

    cases = [("user/stable-diffusion-webui", "stable diffusion", True),
             ("user/stablediffusion-ui", "stable diffusion", False),
             ("user/grok-cli", "grok", True), ("user/ai-grok-wrapper", "grok", True),
             ("user/grokking-algorithms", "grok", False), ("user/xgrok", "grok", False),
             ("user/agent-kit", "agent", True), ("user/agents-sdk", "agent", False),
             ("user/agentic-flow", "agent", False), ("user/c++-lib", "c++", True),
             ("user/c-compiler", "c++", False), ("user/objective-c", "c++", False)]
    for title, term, dropped in cases:
        assert (drop_off_interest([sig(title=title)], {term}) == []) is dropped, title
    assert drop_off_interest([sig(desc="a stable diffusion tool")],
                             {"stable diffusion"}) == []
    long_desc = "x" * 80 + " grok"
    assert drop_off_interest([sig(desc=long_desc)], {"grok"}), "60-char lead rule gone"


# --- 43 -----------------------------------------------------------------------------
@check("43", "a run scored on the ranker's stub says so")
def _no_prompt():
    from topicparser import pipeline, store
    from topicparser.models import Signal

    class _Client:
        def make(self, messages):
            return '{"scored": [{"i": 0, "score": 90, "title": "T", "reason": "R"}]}'

    class _Col:
        source = "github"

        def collect(self, name, cfg):
            return [Signal.make(source="github", title="own/repo", description="d",
                                url="https://github.com/own/repo", date="", profile="AI")]

    with tmpdir() as d:
        store.DB_PATH = os.path.join(d, "t.db")
        store.init_db()
        out = pipeline.run(selected={"AI": {"github": {"topics": ["mcp"]}}},
                           profiles={"AI": {"github": {"topics": ["mcp"]}}},
                           collectors=[_Col()], client=_Client(), threshold=70,
                           x_days=3, gh_days=60, prompt_loader=None)
        assert out["warnings"], "no rules at all must reach the banner"


# --- 44 -----------------------------------------------------------------------------
@check("44", "adjacency stitching is gone and stays gone")
def _no_stitching():
    for rel in [("topicparser", "collectors", "x.py"), ("topicparser", "pipeline.py"),
                ("main.py",), (".env.example",)]:
        text = src(*rel)
        for token in ("stitch_threads", "THREAD_GAP", "THREAD_MAX_LINKS", "overlong"):
            assert token not in text, f"{token} came back in {'/'.join(rel)}"
    from topicparser.collectors import x as xmod
    assert not hasattr(xmod, "stitch_threads")


# --- 04 + 26 + the UI half ----------------------------------------------------------
@check("04/26", "gpt-5 is callable, and one number formatter serves both halves")
def _client_and_numbers():
    from topicparser import llm
    calls = []

    class _Refuses:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    calls.append(kw)
                    if "temperature" in kw:
                        raise Exception("400 Unsupported value: 'temperature' does not "
                                        "support 0.2 with this model")

                    class R:
                        choices = [type("C", (), {"message": type("M", (), {"content": "{}"})})]
                    return R()

    assert llm.OpenAIClient(sdk=_Refuses(), model="gpt-5-mini").make([]) == "{}"
    assert len(calls) == 2 and "temperature" not in calls[1]
    ui = "\n".join(l for l in src("topicparser", "ui", "index.html").splitlines()
                   if not l.strip().startswith("//"))
    assert "toLocaleString" not in ui, "a second number formatter is back"
    assert "el.innerHTML = tr(" not in ui, "the catalogue is being inserted as HTML"
    assert "\x00" not in ui, "a literal NUL makes the file read as binary"


# --- 45 -----------------------------------------------------------------------------
@check("45", "a repost cannot smuggle a stranger into a selected source")
def _reposts_dropped():
    """The author was read off the tweet's own permalink, and a repost renders the
    ORIGINAL tweet — so a list member resharing somebody put that somebody into the
    feed and the .md, from a source the user never selected. Measured on the owner's
    list: 6 of 14 visible entries were reposts."""
    from topicparser.collectors.x import parse_tweet

    class El:
        def __init__(self, href, repost):
            self._href, self._repost = href, repost
        def links(self): return [self._href]
        def inner_text(self): return "hi"
        def tweet_text(self): return "hi"
        def time_datetime(self): return "2026-08-28T10:00:00Z"
        def repost_href(self): return self._repost

    assert parse_tweet(El("/stranger/status/1", "/curator"), "AI") is None
    assert parse_tweet(El("/self/status/2", "/self"), "AI") is None       # self-repost
    assert parse_tweet(El("/foo/status/3", None), "AI") is not None       # ordinary post
    # Keyed on the social context's LINK: keying on its LABEL would break the moment
    # the scraping account's X interface is not English, the trap REPLY_MARKERS sits in.
    # The decision reads the social context's LINK. Keying it on the LABEL would break
    # the moment the scraping account's X interface is not English — the trap
    # REPLY_MARKERS already sits in — so pin the mechanism, not the wording: the parse
    # must ASK the DOM, and the adapter must read that link out of a real element.
    asked = []

    class Spy(El):
        def repost_href(self):
            asked.append(True)
            return None

    parse_tweet(Spy("/foo/status/4", None), "AI")
    assert asked, "parse_tweet stopped asking whether the entry is a repost"

    from topicparser.collectors.x import _ElAdapter
    assert "socialContext" in src("topicparser", "collectors", "x.py"), \
        "the adapter no longer looks for the repost header"
    assert hasattr(_ElAdapter, "repost_href"), "the DOM probe is gone"


@check("46", "a podcast does not share a section with the lab it interviews")
def _podcast_has_its_own_section():
    """`first_party` split the feeds in the config, the collector and the gate, then
    died in the ranker: every feed signal was stamped `feed`, so an interview and
    OpenAI's own release note shared one section in the feed and one in the `.md`.
    Reproduce the FAILURE: build the two signals and demand different keys."""
    from topicparser.models import Signal
    from topicparser.ranker import _source_key, _assemble_topics
    from topicparser import export

    def sig(first_party):
        return Signal.make(source="feed", title="t", description="d",
                           url="https://example.com/a", date="2026-08-30",
                           profile="AI", first_party=first_party)

    assert _source_key(sig(True)) == "feed"
    assert _source_key(sig(False)) == "pod", "a podcast is stamped as a lab post again"
    topics = _assemble_topics([sig(False)], [80], ["Show"], ["r"],
                              {"groups": [], "stale": []})
    assert topics[0]["source"] == "pod", "the topic lost the split"
    keys = [k for k, _ in export._SOURCE_KEYS]
    assert "pod" in keys, "the .md has no podcast section"
    assert keys.index("feed") < keys.index("pod") < keys.index("other")
    ui = src("topicparser", "ui", "index.html")
    assert "'pod'" in ui.split("const SRC_ORDER =")[1].split(";")[0], \
        "the feed stopped drawing the podcast section"


@check("47", "an injected stranger cannot ride a list timeline into the feed")
def _strangers_are_dropped_by_membership():
    """X puts posts by people in no selected source into a list timeline, and the
    cells carry NO marker — measured on the owner's own list, `@lecturehall` and
    `@popsinger` had no placementTracking, no socialContext and the same testids
    as a member's cell. Only the source's own membership can decide. Reproduce the
    failure in both directions, including the fail-open that keeps a run alive."""
    from topicparser.collectors.x import source_handles, drop_strangers
    from topicparser.models import Signal

    def tw(handle):
        return Signal.make(source="x", title=f"@{handle}", description="t",
                           url=f"https://x.com/{handle}/status/1", date="",
                           profile="AI")

    members = {"foo", "bar"}
    kept = drop_strangers([tw("foo"), tw("popsinger")],
                          source_handles("https://x.com/i/lists/9", members=members))
    assert [s.title for s in kept] == ["@foo"], "a stranger reached the feed again"
    # An account timeline may only produce itself, and matching is case-insensitive
    # because X handles are.
    assert source_handles("https://x.com/OpenAI") == {"openai"}
    assert len(drop_strangers([tw("OpenAI")], {"openai"})) == 1
    # Fail OPEN: an unreadable membership costs the filter, never the collection.
    assert source_handles("https://x.com/i/lists/9", members=None) is None
    assert drop_strangers([tw("anyone")], None) == drop_strangers([tw("anyone")], set())
    # And a search is constrained by nothing, since any handle may match a query.
    assert source_handles("https://x.com/search?q=mcp&f=live") is None


@check("48", "the traction numbers reach the file, not just the screen")
def _repo_meta_survives_the_database():
    """`_repo_meta` stamped stars, velocity, the dates and the repo's tags onto every
    topic and `export._traction_lines` was written to print them — but the `.md` is
    assembled from the DATABASE, and `shown_topics` had nowhere to put any of it. So
    the export read those keys off a row that never carried them and printed nothing,
    on every run since the feature landed: 70 GitHub topics in a real export, zero star
    lines. The export tests passed because they hand `_topic_block` a dict with `stars`
    already in it. Reproduce the FAILURE: go through the round trip."""
    from topicparser import store, export, i18n
    with tmpdir() as d:
        store.DB_PATH = os.path.join(d, "t.db")
        store.init_db()
        store.insert_topic(title="a/b", why="w", links=["https://github.com/a/b"],
                           signature="a/b", score=90, profile="AI", source="gh",
                           run_id="r1",
                           meta={"stars": 12400, "velocity": 85.4, "topics": ["llm"],
                                 "created": "2026-07-01", "updated": "2026-08-30"})
        row = store.get_last_run_topics()[0]
        assert row["stars"] == 12400, "the star count died in the database again"
        assert row["topics"] == ["llm"], "the repo tags died in the database again"
        md = export.to_markdown([row], date="2026-09-03")
        assert i18n.t("md.stars_label") in md, "the .md carries no traction again"
        store.close()


@check("49", "an orphan backup cannot eat a profile's rules")
def _lone_backup_is_not_restorable():
    """`prompts/Crypto.bak.txt` held 11 bytes of test text while the profile's real
    rules came from the PACKAGED copy — resolution is per file. `has_backup` said yes,
    so the modal offered «restore», and the swap wrote those 11 bytes in as the live
    prompt AND the absent current (an empty string) over the backup. Press twice and
    the profile scored on `_base` alone. Reproduce the failure: a lone backup."""
    from topicparser import paths, prompts_loader as pl
    with tmpdir() as d:
        real = paths.app_dir
        paths.app_dir = lambda: d
        try:
            os.makedirs(os.path.join(d, "prompts"), exist_ok=True)
            bak = os.path.join(d, "prompts", "Crypto.bak.txt")
            with open(bak, "w", encoding="utf-8") as f:
                f.write("first rules")
            assert not pl.has_backup("Crypto"), "a lone backup is offered again"
            assert pl.restore_profile_prompt("Crypto"), "the swap runs on nothing again"
            assert not os.path.exists(os.path.join(d, "prompts", "Crypto.txt")), \
                "the orphan shadowed the packaged rules"
            with open(bak, encoding="utf-8") as f:
                assert f.read() == "first rules", "the backup was overwritten by nothing"
        finally:
            paths.app_dir = real


@check("50", "a podcast expires on the feed window, not the GitHub one")
def _pod_uses_the_feed_window():
    """`_topic_window` knew three sources and `pod` was not one, so a podcast fell
    through to the GitHub window — the same bug this function exists to prevent, one
    source kind later. Reproduce the failure: narrow GitHub below the feed window,
    which is exactly the configuration that makes it bite."""
    from topicparser import store
    with tmpdir() as d:
        store.DB_PATH = os.path.join(d, "t.db")
        store.init_db()
        pod = store.insert_topic(title="POD", why="w", links=["https://example.com/1"],
                                 signature="p", score=80, profile="AI", source="pod")
        store._backdate_topic(pod, 10)
        store.cleanup_topics(x_days=3, gh_days=5, feed_days=30)
        assert store.get_recent_topics(days=365), \
            "the podcast expired on the GitHub window again"
        store.close()


@check("51", "both feed lists are validated, as the UI claims")
def _interviews_are_validated_too():
    """`index.html` says of SOURCE_SHAPE: "Same shapes Python enforces
    (config._check_sources)". The 08-29 split added a second feed list and the
    validator kept checking only the first, so the mirror was one rule short and a
    hand-edited profiles.yaml sailed through."""
    from topicparser import config
    assert config.validate_profiles(
        {"profiles": {"AI": {"feeds": {"interviews": ["not-a-url"]}}}}), \
        "a junk podcast URL is accepted again"
    assert config.validate_profiles(
        {"profiles": {"AI": {"feeds": {"urls": ["https://a.dev/f.xml"],
                                       "interviews": ["https://b.dev/p.xml"]}}}}) == []


@check("C1", "the feed ceiling is declared and its bite is visible")
def _feed_ceiling_is_observable():
    """`DEFAULT_LIMIT = 25` lived in `feeds.py` and nowhere else — `main` built
    `FeedCollector()` with no arguments, so an `.env` value had nowhere to land — and
    whether it BOUND could not be read from the run log, because the cap applies before
    the freshness filter and the log only holds survivors. The number is deliberately
    unchanged; this proves it is declared in all three places and that a truncated feed
    now says so."""
    from topicparser import settings
    from topicparser.collectors import feeds
    import inspect, re

    documented = settings.read_env(os.path.join(ROOT, ".env.example"))
    assert int(documented["FEED_MAX_ITEMS"]) == feeds.DEFAULT_LIMIT, \
        "the feed ceiling drifted from what .env.example documents"
    main_src = src("main.py")
    fallbacks = dict(re.findall(r'config\.env_num\("([A-Z_]+)",\s*([0-9.]+)', main_src))
    assert int(float(fallbacks["FEED_MAX_ITEMS"])) == feeds.DEFAULT_LIMIT, \
        "main.py stopped wiring the feed ceiling"
    assert inspect.signature(feeds.FeedCollector.__init__).parameters["limit"].default \
        == feeds.DEFAULT_LIMIT

    items = "".join(f"<item><title>t{i}</title><link>https://e.dev/{i}</link>"
                    f"<pubDate>Mon, 01 Sep 2026 10:00:00 GMT</pubDate></item>"
                    for i in range(40))
    col = feeds.FeedCollector(limit=5)
    col._fetch = lambda url: f"<rss><channel>{items}</channel></rss>".encode()
    col.collect("AI", {"feeds": {"urls": ["https://e.dev/f.xml"]}})
    assert col.stats and col.stats[0]["capped"] is True, \
        "a truncated feed reads as a quiet one again"


@check("52", "a run still renders a feed at all")
def _feed_groups_cannot_drift_from_the_order():
    """The worst bug this project has shipped, and it shipped to BOTH repos.

    `1843cfb` added 'pod' to `SRC_ORDER` and to `sourceOf` and left the grouping
    literal in `renderResults` at four keys. The throw is not in the cards — it is the
    LOOP: `for(const key of SRC_ORDER)` reaches 'pod', `groups['pod']` is undefined and
    `list.length` raises. So EVERY run rendered nothing at all, podcast topic or not:
    a blank feed, the status stuck on the running message, the `.md` button armed
    over an empty screen, after sixteen minutes and a paid scoring pass. Live from 2026-09-02 to
    2026-09-04, unnoticed only because the last real run was 08-30.

    Found by DRIVING the stub harness, not by reading: both places look right on their
    own. Reproduce the failure by demanding the two can no longer be written apart."""
    ui = src("topicparser", "ui", "index.html")
    body = ui[ui.index("function renderResults("):]
    body = body[:body.index("\n}")]
    line = next(l for l in body.splitlines() if "const groups" in l)
    assert "SRC_ORDER" in line, \
        f"the feed groups topics by a hand-written list again: {line.strip()}"
    order = ui.split("const SRC_ORDER =")[1].split(";")[0]
    keys = [k.strip().strip("'\"") for k in order.strip(" []").split(",")]
    assert "pod" in keys and len(keys) == 5, f"SRC_ORDER changed shape: {keys}"


@check("53", "a stopped profile still says what it scraped")
def _stop_keeps_the_scrape_numbers():
    """Stop is pressed BECAUSE a scrape is dragging, and the numbers that say why were
    the ones thrown away: `raise RunCancelled()` sat after collecting but BEFORE the
    profile's debug row was built, so the interrupted profile left no trace at all — no
    signal count, nothing per URL. That is the opposite of the rule those rows exist
    for, and a stopped run is one the owner has already partly paid for. The row is
    registered before the check now; the rest of it is filled in as the run gets there.
    Reproduce the failure: stop DURING the scrape and demand the row."""
    import json, threading, glob
    from topicparser import pipeline, store
    from topicparser.cancellation import RunCancelled
    from topicparser.models import Signal

    with tmpdir() as d:
        store.DB_PATH = os.path.join(d, "t.db")
        store.init_db()
        stop = threading.Event()

        class XCol:
            source = "x"
            stats = [{"url": "https://x.com/i/lists/1", "tweets": 48,
                      "scrolls": 80, "strangers": 2}]
            def collect(self, name, cfg):
                stop.set()          # pressed mid-scrape, the case that matters
                return [Signal.make(source="x", title="t", description="d",
                                    url="https://x.com/u/status/1",
                                    date="2026-09-04T00:00:00Z", profile="AI")]

        try:
            pipeline.run(selected=["AI"], profiles={"AI": {"x": {"lists": [{"id": "1"}]}}},
                         collectors=[XCol()], client=None, threshold=70, x_days=3,
                         gh_days=60, debug_dir=d, cancel_event=stop)
        except RunCancelled:
            pass
        log = json.load(open(glob.glob(os.path.join(d, "run-*.json"))[0], encoding="utf-8"))
        prof = log["profiles"].get("AI")
        assert prof is not None, "a stopped profile leaves no trace in the run log again"
        assert prof["x_sources"][0]["tweets"] == 48, "the scrape numbers died with the stop"
        store.close()


def main() -> int:
    failed = []
    for finding, what, fn in CHECKS:
        try:
            fn()
            print(f"  PASS  [{finding:>5}] {what}")
        except Exception as e:
            failed.append((finding, what, e))
            print(f"  FAIL  [{finding:>5}] {what}\n          {type(e).__name__}: {e}")
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} closed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
