"""The 2026-08-22 review, batch A: fixes that cannot change what the scorer sees.

Every test here names the failure the finding produces. The batch rule is what makes
them one file: none of these edits touches a prompt, a signal's text or the number of
signals, so the run table's three rows stay comparable across this commit.
"""
import json
import os
import re

import pytest

from topicparser import api as api_mod
from topicparser import config, export, llm, pipeline, prefilter, ranker, settings, store, tuning

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = open(os.path.join(ROOT, "topicparser", "ui", "index.html"), encoding="utf-8").read()
XSRC = open(os.path.join(ROOT, "topicparser", "collectors", "x.py"), encoding="utf-8").read()


# --- 01: a reply SHAPE the parsers never met must not kill the run ------------------
# `{"drop": null}` is valid JSON, so it sails past the json.loads guard and dies on the
# iteration instead — after fifteen minutes of scraping and every paid scoring call.
# The gates already wrap their parser in try; dedup and clustering do not, so those two
# are the live path. A refusal answers `content = None`, which lands in the same place.
@pytest.mark.parametrize("raw", ['{"drop": null}', '{"drop": 3}', '{"drop": "1,2"}',
                                 '{"drop": {"a": 1}}', "{}", "[]", "not json", None])
def test_drop_parsers_never_raise(raw):
    assert ranker.parse_dedup(raw) == set()
    assert ranker.parse_xgate(raw) == set()


@pytest.mark.parametrize("raw", ['{"groups": null}', '{"groups": ["x"]}',
                                 '{"groups": [{"indices": null}]}', '{"stale": null}',
                                 '{"groups": [{}]}', "not json", None])
def test_parse_groups_never_raises(raw):
    out = ranker.parse_groups(raw)
    assert isinstance(out["groups"], list) and isinstance(out["stale"], list)


@pytest.mark.parametrize("raw", ['{"scored": null}', '{"scored": [{"i": null}]}',
                                 '{"scored": "x"}', None])
def test_parse_scored_never_raises(raw):
    assert ranker.parse_scored(raw) == []


def test_a_dying_run_still_writes_its_debug_log(tmp_path, monkeypatch):
    # The log is the only record of what the run scored, and it was written after the
    # profile loop returned — so the one failure mode worth diagnosing produced nothing.
    def boom(*a, **kw):
        raise RuntimeError("parser died")

    for name, val in [("cleanup_topics", None), ("prune_star_history", None),
                      ("drop_stagnant_repos", None)]:
        monkeypatch.setattr(pipeline.store, name, lambda *a, **kw: val)
    monkeypatch.setattr(pipeline.store, "detect_trending", lambda **kw: [])
    monkeypatch.setattr(pipeline.store, "seen_links", lambda **kw: set())
    monkeypatch.setattr(pipeline.store, "get_banned_repos", lambda: set())
    monkeypatch.setattr(pipeline.store, "get_recent_topics", lambda **kw: [])
    monkeypatch.setattr(pipeline, "_collect_and_score", boom)
    with pytest.raises(RuntimeError):
        pipeline.run(selected={"AI": {}}, profiles={"AI": {}}, collectors=[], client=None,
                     threshold=70, x_days=3, gh_days=60, debug_dir=str(tmp_path))
    assert list(tmp_path.glob("run-*.json")), "no debug log written for the failed run"


# --- 02: "login" ANYWHERE in the url is not a login redirect ------------------------
# @loginhelper is a real handle and "openai login" is a legal search; both made the
# whole X collection raise XSessionExpired, which `collect` deliberately does not catch.
@pytest.mark.parametrize("url,expired", [
    ("https://x.com/loginhelper", False),
    ("https://x.com/search?q=openai%20login", False),
    ("https://x.com/i/flow/login", True),
    ("https://x.com/login", True),
    ("https://twitter.com/login?redirect_after_login=%2Fhome", True),
])
def test_only_a_real_login_page_reads_as_an_expired_session(url, expired):
    from topicparser.collectors.x import is_login_url
    assert is_login_url(url) is expired


# --- 03: the card's first link decides what Ban and Open do -------------------------
def test_a_mixed_cluster_leads_with_its_github_member():
    # The card shows a GitHub badge and stars from the cluster's repo member, while Ban
    # and Open both read links[0] — a tweet there banned the tweet URL: a junk row in
    # `banned_repos`, the repo still live, `kept` still set, and the card gone from the
    # screen so the user believes it worked.
    from topicparser.models import Signal
    tw = Signal.make(source="x", title="@dev", description="look at this",
                     url="https://x.com/dev/status/999", date="", profile="AI")
    gh = Signal.make(source="github", title="own/repo", description="the repo",
                     url="https://github.com/own/repo", date="", profile="AI", stars=1200)
    topics = ranker._assemble_topics(
        [tw, gh], [80, 75], ["t", "g"], ["r", "r"],
        {"groups": [{"indices": [0, 1], "title": "One story", "why": "w"}], "stale": []})
    assert topics[0]["source"] == "gh"
    assert topics[0]["links"][0] == "https://github.com/own/repo"


# --- 05 + 37: a key in the ENVIRONMENT is a configured key --------------------------
def _api(tmp_path, **kw):
    return api_mod.Api(profiles={"profiles": {}}, build_collectors=lambda: [],
                       build_client=lambda: None, threshold=70, x_days=3, gh_days=60,
                       profiles_path=str(tmp_path / "p.yaml"),
                       cookies_path=str(tmp_path / "c.json"), **kw)


def test_keys_from_the_environment_count_as_present(tmp_path, monkeypatch):
    # `GITHUB_TOKEN=… python main.py` runs fine — the pipeline reads os.environ — but
    # the UI read the .env FILE only, so the first-run guide opened over a working app.
    monkeypatch.setattr(api_mod.paths, "app_dir", lambda: str(tmp_path))
    monkeypatch.setenv("GITHUB_TOKEN", "gh-from-env")
    monkeypatch.setenv("OPENAI_API_KEY", "oa-from-env")
    state = _api(tmp_path).setup_state()
    assert state["needs_onboarding"] is False
    assert "GITHUB_TOKEN" not in state["missing"]


def test_a_key_in_the_environment_is_verified_not_called_missing(tmp_path, monkeypatch):
    # 37 was half right: ABSENT must keep blocking the run (that is what the guide is
    # for), but a key that lives only in the environment is not absent, and the
    # preflight named it "rejected" and refused to start.
    monkeypatch.setattr(api_mod.paths, "app_dir", lambda: str(tmp_path))
    monkeypatch.setenv("GITHUB_TOKEN", "gh-from-env")
    monkeypatch.setenv("OPENAI_API_KEY", "oa-from-env")
    monkeypatch.setattr("requests.get",
                        lambda *a, **k: type("R", (), {"status_code": 200,
                                                       "json": lambda self: {}})())
    assert _api(tmp_path).check_keys()["rejected"] == []


# --- 15: a newline in a text knob writes any line it likes into .env ----------------
def test_a_newline_in_a_knob_value_is_refused():
    assert tuning.validate({"OFF_INTEREST": "crypto\nGITHUB_TOKEN=hijacked"})
    assert tuning.validate({"OFF_INTEREST": "crypto, agents"}) == []


# --- 16: a ban is a ban whatever the case ------------------------------------------
def test_a_ban_matches_the_repo_whatever_case_it_was_typed_in(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "t.db"))
    store.init_db()
    _api(tmp_path).ban_repo("https://github.com/OpenAI/Whisper")
    from topicparser.models import Signal
    sig = Signal.make(source="github", title="openai/whisper", description="",
                      url="https://github.com/openai/whisper", date="", profile="AI")
    assert prefilter.drop_banned([sig], store.get_banned_repos()) == []


# --- 17: the second wipe must not eat the first backup ------------------------------
def test_each_wipe_keeps_its_own_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "topics.db"))
    store.init_db()
    first = store.reset_all(topics=True)
    second = store.reset_all(topics=True)
    assert first and second and first != second
    assert os.path.exists(first) and os.path.exists(second)


# --- 18: a cookie export with a junk expiry ----------------------------------------
def test_a_bad_expiry_in_a_cookie_export_is_an_error_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(api_mod.paths, "app_dir", lambda: str(tmp_path))
    raw = json.dumps([{"name": "auth_token", "value": "v", "domain": ".x.com",
                       "path": "/", "expirationDate": "never"}])
    out = _api(tmp_path).import_cookies(raw)
    assert out.get("errors")


# --- 20: star history retention is not the GitHub freshness window ------------------
def test_star_history_retention_has_its_own_number():
    src = open(os.path.join(ROOT, "topicparser", "pipeline.py"), encoding="utf-8").read()
    assert "prune_star_history(days=gh_days)" not in src
    assert isinstance(store.STAR_HISTORY_DAYS, int)


# --- 22: 62 sequential calls with no reaction to a rate limit -----------------------
def test_measure_tracked_stops_asking_once_github_rate_limits(monkeypatch):
    from topicparser.collectors import github as gh_mod

    calls = []

    class _Resp:
        status_code = 403

        def raise_for_status(self):
            raise Exception("403 rate limited")

    def fake_get(url, **kw):
        calls.append(url)
        return _Resp()

    from topicparser import store as store_mod
    monkeypatch.setattr(store_mod, "get_tracked_repos", lambda: [f"o/r{i}" for i in range(50)])
    monkeypatch.setattr(gh_mod.requests, "get", fake_get)
    col = gh_mod.GitHubCollector(token="t")
    col.warn = lambda msg: None
    col.measure_tracked()
    assert len(calls) < 5, "kept hammering a rate-limited API for every tracked repo"


# --- 04: the model list offers models the client cannot call -----------------------
def test_a_model_that_refuses_temperature_is_learned_not_listed():
    # Measured live: gpt-5 and gpt-5-mini answer 400 "Only the default (1) value is
    # supported", 400 is not retried, so every batch fails and the run scores nothing.
    calls = []

    class _Refuses:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    calls.append(kw)
                    if "temperature" in kw:
                        raise Exception("Error code: 400 - Unsupported value: "
                                        "'temperature' does not support 0.2 with this model")
                    class R:
                        choices = [type("C", (), {"message": type("M", (), {"content": "{}"})})]
                    return R()

    client = llm.OpenAIClient(sdk=_Refuses(), model="whatever-next")
    assert client.make([{"role": "user", "content": "x"}]) == "{}"
    assert len(calls) == 2 and "temperature" not in calls[1]
    calls.clear()
    client.make([{"role": "user", "content": "x"}])          # remembered, no second cost
    assert len(calls) == 1 and "temperature" not in calls[0]

    # learning must not eat the ONE attempt a client configured with retries=1 has
    calls.clear()
    lean = llm.OpenAIClient(sdk=_Refuses(), model="whatever-next", retries=1)
    assert lean.make([{"role": "user", "content": "x"}]) == "{}"

    ok = []

    class _Accepts:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    ok.append(kw)
                    class R:
                        choices = [type("C", (), {"message": type("M", (), {"content": "{}"})})]
                    return R()

    llm.OpenAIClient(sdk=_Accepts(), model="gpt-4.1-mini").make([{"role": "user", "content": "x"}])
    assert ok[0]["temperature"] == 0.2


# --- 34: the export is named after the run it holds ---------------------------------
def test_the_md_is_named_after_the_run_it_exports():
    assert api_mod._md_filename(run_id="2026-08-19T22:10:00+00:00") == "topics-2026-08-19.md"


# --- 35: the seen-window and the freshness window must agree ------------------------
def test_the_feed_window_defaults_the_same_way_on_both_sides():
    pf = open(os.path.join(ROOT, "topicparser", "prefilter.py"), encoding="utf-8").read()
    st = open(os.path.join(ROOT, "topicparser", "store.py"), encoding="utf-8").read()
    assert "feed_days if feed_days is not None\n                                     else gh_days" not in st
    assert "x_days if feed_days is None else feed_days" in pf


# --- 36: a profile name is a FILENAME on Windows too --------------------------------
@pytest.mark.parametrize("name", ["a:b", "a*b", "a?b", "a<b", 'a"b', "a|b"])
def test_windows_illegal_characters_are_refused_in_a_profile_name(name):
    assert config.validate_profile_name(name)


# --- 41: one source map, not three --------------------------------------------------
def test_the_export_reads_the_ranker_source_map():
    src = open(os.path.join(ROOT, "topicparser", "export.py"), encoding="utf-8").read()
    assert "_SOURCE_KEY" in src


# --- 24/25/26/27: the UI half ------------------------------------------------------
def test_saving_a_profile_does_not_validate_the_empty_add_fields():
    # Every Save toasted "bad feed URL", "bad handle", "bad topic" beside the green
    # "saved" — flushPending pushed every empty add box through the validator.
    block = re.search(r"function flushPending\(\)\{.*?\n\}", UI, re.S).group(0)
    assert "if(!inp.value.trim()) return;" in block


def test_numbers_have_one_formatter():
    body = "\n".join(l for l in UI.splitlines() if not l.strip().startswith("//"))
    assert "toLocaleString" not in body


def test_the_catalogue_is_inserted_as_text_not_html():
    assert "el.innerHTML = tr(" not in UI


def test_renaming_a_profile_carries_its_picker_selection():
    assert "remapPickerKeys" in UI


# --- 07/21/30: a comment that describes something else ------------------------------
# The README is EDITED here and lives only in the public repo, so `docs/` not shipping
# is exactly why this half skips there — same split as test_knob_docs.py.
_README = os.path.join(ROOT, "docs", "public", "README.md")


@pytest.mark.skipif(not os.path.exists(_README), reason="docs/ does not ship")
def test_the_readme_does_not_promise_an_editor_for_the_shared_rules():
    readme = open(_README, encoding="utf-8").read()
    assert "the app edits both in a modal" not in readme


def test_the_session_docstring_does_not_claim_one_browser_per_run():
    assert "One shared browser+context for a whole run" not in XSRC


# --- 38/39: housekeeping ------------------------------------------------------------
def test_every_requirement_is_pinned():
    req = open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
    for line in req.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        assert "==" in line, f"unpinned requirement: {line}"


def test_store_imports_nothing_it_does_not_use():
    src = open(os.path.join(ROOT, "topicparser", "store.py"), encoding="utf-8").read()
    head = src.split("\n")[3]
    assert "Float" not in head and " text" not in head


def test_a_ban_written_before_the_lowercase_fix_still_works(tmp_path, monkeypatch):
    # The rows already in `banned_repos` carry GitHub's own capitals. If only the
    # WRITE side were normalised they would silently stop matching: the repo returns
    # to the feed while still sitting in the banned list.
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "t.db"))
    store.init_db()
    store.ban_repo("OpenAI/Whisper")                     # a pre-fix row, as typed
    from topicparser.models import Signal
    sig = Signal.make(source="github", title="openai/whisper", description="",
                      url="https://github.com/openai/whisper", date="", profile="AI")
    assert prefilter.drop_banned([sig], store.get_banned_repos()) == []
    # and it must still be possible to LIFT that ban from the screen, where the click
    # now normalises the name on the way in
    api_mod.Api(profiles={"profiles": {}}, build_collectors=lambda: [],
                build_client=lambda: None, threshold=70, x_days=3,
                gh_days=60).unban_repo("https://github.com/OpenAI/Whisper")
    assert store.get_banned_repos() == set()


def test_a_client_that_answers_none_loses_nothing(monkeypatch):
    # `resp.choices[0].message.content` is None on a refusal or an empty answer, and it
    # reaches the same parsers. json.loads(None) raises TypeError one step earlier than
    # the shape guards, so this is the client's failure mode, not the model's.
    class _None:
        def make(self, messages):
            return None

    topics = [{"title": "T", "why": "w", "score": 80, "links": ["u"]}]
    assert ranker.dedup_shown(topics, ["something shown"], _None()) == topics
    assert ranker.gate_tweets([], _None()) == set()


# --- the hole this session's own mistake found --------------------------------------
def test_a_run_with_no_scoring_prompt_at_all_says_so(tmp_path, monkeypatch):
    """An EMPTY prompt file raised a banner; NO prompt loader raised nothing.

    That is the louder failure of the two — the ranker falls back to its 14-line
    `DEFAULT_SYSTEM`, both gates are skipped for want of a prompt, and the run produces
    a full, plausible feed scored by somebody else's rules. Measured live on
    2026-08-22: 809 topics against the 20-49 a real run gives, 274 signals sitting
    exactly on 70, `xgate: 0`, `feedgate: 0`, and every `reason` in English.
    """
    from topicparser.models import Signal

    class _Client:
        def make(self, messages):
            return '{"scored": [{"i": 0, "score": 90, "title": "T", "reason": "R"}]}'

    sig = Signal.make(source="github", title="own/repo", description="d",
                      url="https://github.com/own/repo", date="", profile="AI")

    class _Col:
        source = "github"

        def collect(self, name, cfg):
            return [sig]

    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "t.db"))
    store.init_db()
    out = pipeline.run(selected={"AI": {"github": {"topics": ["mcp"]}}},
                       profiles={"AI": {"github": {"topics": ["mcp"]}}},
                       collectors=[_Col()], client=_Client(), threshold=70,
                       x_days=3, gh_days=60, prompt_loader=None)
    assert out["warnings"], "a run scored by the ranker's stub must say so"
