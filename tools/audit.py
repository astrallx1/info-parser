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
