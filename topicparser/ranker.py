import json
import re
from topicparser.models import NICHE, Signal
from topicparser.cancellation import RunCancelled

_CYRILLIC = re.compile(r"[Ѐ-ӿ]")

# Mechanical repair, NOT scoring criteria — that is why it lives here and not in
# prompts/. Nothing about WHICH signals win is decided by this text.
def _relang_system(language: str) -> str:
    return (
        f"You rewrite short product descriptions into {language.upper()}.\n"
        "You get a JSON object of numbered descriptions written in the wrong language. "
        f"Rewrite each one in {language}, keeping the SAME meaning and length (1-2 "
        "sentences) and keeping product / project / tech names verbatim in their "
        "original script. Do not translate word-for-word if that reads badly — "
        f"describe the same thing in natural {language}.\n"
        'Return STRICT JSON, nothing else: {"fixed":{"<index>":"<rewritten text>"}}'
    )


# Fallback used only when no per-profile prompt is supplied (tests / safety).
DEFAULT_SYSTEM = (
    "You score Twitter/X post TOPIC ideas (not full posts) for a personal account.\n"
    f"{NICHE}\n"
    "You are given numbered raw signals (GitHub repos / tweets). SCORE every "
    "signal 0-100 on how good an on-niche topic it is; give signals scoring "
    ">= 70 a short English title.\n"
    'Return STRICT JSON: {"scored":[{"i":int,"score":int,"reason":str,'
    '"title":str}]}. "scored" must include EVERY signal by its index i.'
)

# Fallback used only when no dedup prompt is supplied (tests / safety).
# The real one lives in prompts/_dedup.txt.
DEFAULT_DEDUP = (
    "You are a de-duplicator. You get a numbered list of CANDIDATE topic titles "
    "and a list of themes ALREADY SHOWN to the user in earlier runs. Return the "
    "indices of candidates whose STORY is already covered by an already-shown "
    "theme (same product/model/launch/news), so the user is not shown it twice. "
    "A genuinely new angle or new development on the same subject is NOT a "
    "duplicate — keep it. When unsure, KEEP (do not drop).\n"
    'Return STRICT JSON: {"drop":[int,...]} (indices into candidates).'
)

# Fallback used only when no X-gate prompt is supplied (tests / safety).
# The real one lives in prompts/_xgate.txt.
DEFAULT_XGATE = (
    "You filter tweets for someone who writes their OWN posts. For each numbered "
    "tweet ask: is there a raw FACT here to build a post around, or did the author "
    "already say everything? Return the indices where the AUTHOR ALREADY SAID "
    "EVERYTHING — someone's find presented as a find, a finished argument or essay, "
    "one more person's reading of someone else's release, a personal story, an ad. "
    "KEEP a first-party announcement, a concrete new capability, a checkable fact "
    "about a named company however hyped the wrapper, and any joinable opportunity. "
    "WHEN IN DOUBT, KEEP.\n"
    'Return STRICT JSON: {"drop":[int,...]}.'
)

# Fallback used only when no grouping prompt is supplied (tests / safety).
# The real one lives in prompts/_group.txt.
DEFAULT_GROUP = (
    "You find SAME-STORY clusters among pre-scored topic signals. A cluster = "
    "2+ signals about the SAME product/repo/model/launch/piece of news, "
    "regardless of author or platform. Different products or events are NOT a "
    "cluster. Signals in no cluster are simply not mentioned. Also list in "
    '"stale" the indices whose story is already in already_shown_themes with '
    "nothing genuinely new.\n"
    'Return STRICT JSON: {"groups":[{"indices":[int,...],"title":str,'
    '"why":str}],"stale":[int,...]}. "title" in English, "why" in the same '
    "language as the signals' own reasons."
)

def build_messages(signals: list[Signal], recent_titles: list[str],
                   system_prompt: str | None = None) -> list[dict]:
    payload = {
        "already_shown_themes": recent_titles,
        "signals": [{"i": idx, "source": s.source, "title": s.title,
                     "description": s.description, "url": s.url, "date": s.date,
                     "stars": s.stars, "velocity": s.velocity}
                    for idx, s in enumerate(signals)],
    }
    return [
        {"role": "system", "content": system_prompt or DEFAULT_SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]

def build_group_messages(signals: list[Signal], scores: list[int],
                         recent_titles: list[str],
                         group_prompt: str | None = None) -> list[dict]:
    payload = {
        "already_shown_themes": recent_titles,
        "signals": [{"i": idx, "source": s.source, "title": s.title,
                     "description": s.description, "url": s.url,
                     "score": scores[idx]}
                    for idx, s in enumerate(signals)],
    }
    return [
        {"role": "system", "content": group_prompt or DEFAULT_GROUP},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]

def _listed(data, key) -> list:
    """The value at `key`, but only when it is a LIST.

    A reply is model output, not a contract: `{"drop": null}` is valid JSON, so it
    sails past the json.loads guard and dies on the iteration instead — after the
    scrape and every paid scoring call. The gates wrap their parser in a try; the
    dedup and clustering calls do not, so a shape nobody had met killed the run and
    the debug log with it. Anything that is not a list means "nothing here"."""
    if not isinstance(data, dict):
        return []
    v = data.get(key)
    return v if isinstance(v, list) else []


def parse_scored(raw: str) -> list[dict]:
    """Model output, not a contract: `score` has arrived as `null` and as `"high"`,
    both of which `int()` raises on. An entry that cannot be read is SKIPPED rather
    than fatal — it then counts as omitted, which is precisely what the gap-fill
    re-asks. Out-of-range numbers are clamped instead of dropped: the model meant a
    verdict, only the scale slipped."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    out = []
    for s in _listed(data, "scored"):
        if not isinstance(s, dict):
            continue
        # No `score` at all is an OMISSION, not a verdict of 0: defaulting it made the
        # signal count as scored, so the gap-fill never re-asked it. The retry
        # machinery exists against a model that leaves things out; this was the hole
        # at the one place it leaves out a FIELD rather than a whole entry.
        if "i" not in s or "score" not in s:
            continue
        try:
            i, score = int(s["i"]), int(s["score"])
        except (TypeError, ValueError):
            continue
        out.append({"i": i, "score": max(0, min(100, score)),
                    "reason": s.get("reason", ""), "title": s.get("title", "")})
    return out

def build_dedup_messages(topics: list[dict], recent_titles: list[str],
                         prompt: str | None = None) -> list[dict]:
    payload = {
        "already_shown": recent_titles,
        "candidates": [{"i": idx, "title": t.get("title", "")}
                       for idx, t in enumerate(topics)],
    }
    return [
        {"role": "system", "content": prompt or DEFAULT_DEDUP},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]

def parse_dedup(raw: str) -> set[int]:
    """Dedup reply -> set of candidate indices to drop. Never raises: a broken
    reply drops NOTHING (a genuine topic must never be lost to a parse error)."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return set()
    return {int(i) for i in _listed(data, "drop") if isinstance(i, (int, float))}

def dedup_shown(topics: list[dict], recent_titles: list[str], client,
                prompt: str | None = None, cancel_event=None) -> list[dict]:
    """Drop assembled topics whose story was already shown in a PRIOR run. A
    SEPARATE, focused call (just titles vs shown themes) — the weak model handles
    this small task far better than judging it inside the overloaded group call.
    Skips the call entirely when nothing has been shown yet."""
    if not recent_titles or not topics:
        return topics
    if cancel_event is not None and cancel_event.is_set():
        raise RunCancelled()
    try:
        raw = client.make(build_dedup_messages(topics, recent_titles, prompt))
    except RunCancelled:
        raise
    except Exception:
        return topics     # a dead call drops NOTHING — same contract as a broken reply
    drop = parse_dedup(raw)
    return [t for i, t in enumerate(topics) if i not in drop]

def build_xgate_messages(pairs: list[tuple[int, "Signal"]],
                         prompt: str | None = None) -> list[dict]:
    """`pairs` = (survivor index, tweet). Indices are the caller's, so the reply maps
    straight back onto the survivor list."""
    payload = {"tweets": [{"i": i, "author": s.title, "text": s.description}
                          for i, s in pairs]}
    return [
        {"role": "system", "content": prompt or DEFAULT_XGATE},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]

def parse_xgate(raw: str) -> set[int]:
    """Gate reply -> set of indices to drop. Never raises: a broken reply drops
    NOTHING (same contract as parse_dedup)."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return set()
    return {int(i) for i in _listed(data, "drop") if isinstance(i, (int, float))}

def gate_tweets(survivors: list[Signal], client, prompt: str | None = None,
                cancel_event=None) -> set[int]:
    """Re-judge ONLY the tweets among the survivors: did the author already say
    everything, or is there raw material left to write about?

    The scoring call carries the whole profile prompt over hundreds of signals, and
    the weak model never gets as far as the own-angle rules — a finished opinion or
    a "look what I found" demo parks at 70 run after run, even when the prompt names
    it verbatim. Three prompt rewrites did not hold it. This is the same escape used
    for clustering and cross-run dedup: one tiny question, tiny output.

    Returns indices INTO `survivors`. GitHub signals are never sent and never
    dropped. Any failure (bad JSON, dead API) drops nothing — the gate improves a
    run, it must not be able to break one."""
    pairs = [(i, s) for i, s in enumerate(survivors) if s.source == "x"]
    if not pairs:
        return set()
    if cancel_event is not None and cancel_event.is_set():
        raise RunCancelled()
    allowed = {i for i, _ in pairs}
    try:
        drop = parse_xgate(client.make(build_xgate_messages(pairs, prompt)))
    except RunCancelled:
        raise
    except Exception:
        return set()
    return drop & allowed

DEFAULT_FEEDGATE = """You judge posts from a lab's own blog or YouTube channel.
Return STRICT JSON {"drop":[i,...]} listing the posts that are company PR rather
than the event itself. Drop nothing you are unsure about."""


def build_feedgate_messages(pairs: list[tuple[int, "Signal"]],
                            prompt: str | None = None) -> list[dict]:
    """`pairs` = (survivor index, feed post). Indices are the caller's, so the reply
    maps straight back onto the survivor list."""
    payload = {"posts": [{"i": i, "title": s.title, "text": s.description}
                         for i, s in pairs]}
    return [
        {"role": "system", "content": prompt or DEFAULT_FEEDGATE},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def gate_feeds(survivors: list[Signal], client, prompt: str | None = None,
               cancel_event=None) -> set[int]:
    """Re-judge ONLY the official-source posts among the survivors: is the post the
    EVENT, or the company talking about itself?

    Same escape as the tweet gate, for the same measured reason. A lab's blog is its
    marketing channel as much as its newsroom, so customer case studies, analyst
    awards and product how-tos arrive wearing a first-party badge and the scorer waves
    them through. The rule written into `_base.txt` did hold them down (42 -> 25 of 69
    over three replays a side) but took GitHub and X with it (>=70 per replay went
    40/34/42 -> 33/30/25), because a shared prompt cannot be scoped to one source.
    A separate call can: nothing but feed posts is ever sent.

    Returns indices INTO `survivors`. Any failure (bad JSON, dead API, an index that
    is not a feed post) drops nothing."""
    pairs = [(i, s) for i, s in enumerate(survivors) if s.source == "feed"]
    if not pairs:
        return set()
    if cancel_event is not None and cancel_event.is_set():
        raise RunCancelled()
    allowed = {i for i, _ in pairs}
    try:
        drop = parse_xgate(client.make(build_feedgate_messages(pairs, prompt)))
    except RunCancelled:
        raise
    except Exception:
        return set()
    return drop & allowed

def parse_groups(raw: str) -> dict:
    """Grouping reply -> {"groups":[{indices,title,why}], "stale":[i,...]}.
    Never raises: topic assembly is code-side, a broken reply just means
    'no clusters found' (every survivor becomes its own topic)."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {"groups": [], "stale": []}
    groups = []
    for g in _listed(data, "groups"):
        if not isinstance(g, dict):
            continue
        idxs = [int(i) for i in _listed(g, "indices") if isinstance(i, (int, float))]
        if not idxs:
            continue
        groups.append({"indices": idxs, "title": g.get("title", ""),
                       "why": g.get("why", "")})
    stale = [int(i) for i in _listed(data, "stale") if isinstance(i, (int, float))]
    return {"groups": groups, "stale": stale}


# A signal knows where it came from; a URL only sometimes does. The feed, the export
# and the DB all used to sniff `links[0]` for "github.com", which cannot tell a lab's
# blog post from any other address — so every official-source topic fell into "other".
# The mapping happens ONCE, here, and travels with the topic from now on.
_SOURCE_KEY = {"github": "gh", "x": "tw", "feed": "feed"}
# A cluster can mix sources. GitHub wins because that member carries the stars and the
# repo card; X beats a feed because the tweet is what the reader replies to.
_SOURCE_RANK = ["gh", "tw", "feed", "other"]


def _source_key(signal) -> str:
    return _SOURCE_KEY.get(getattr(signal, "source", "") or "", "other")


def _cluster_source(signals) -> str:
    keys = {_source_key(s) for s in signals}
    return next((k for k in _SOURCE_RANK if k in keys), "other")


def _assemble_topics(survivors: list[Signal], scores: list[int],
                     titles: list[str], reasons: list[str],
                     grouped: dict) -> list[dict]:
    """Code-side topic assembly — the coverage guarantee. Every survivor ends up
    in exactly one topic: LLM-named clusters first, everything else a singleton."""
    n = len(survivors)
    stale = {i for i in grouped["stale"] if 0 <= i < n}
    used: set[int] = set()
    topics: list[dict] = []
    for g in grouped["groups"]:
        idxs = [i for i in g["indices"] if 0 <= i < n and i not in used]
        if len(idxs) < 2:            # not a real cluster once cleaned -> singletons
            continue
        # hard rule (enforced in code because the LLM keeps breaking it):
        # different repos are ALWAYS different stories. >1 distinct GitHub repo
        # in one cluster = a category mix -> reject, members become singletons.
        repos = {survivors[i].url for i in idxs
                 if "github.com" in (survivors[i].url or "")}
        if len(repos) > 1:
            continue
        used.update(idxs)
        if all(i in stale for i in idxs):
            continue                 # whole story already shown
        # repo meta for the feed card comes from the cluster's GitHub member (if any)
        rep = next((survivors[i] for i in idxs if survivors[i].source == "github"),
                   survivors[idxs[0]])
        # `rep` leads the links: the card takes its badge, stars and repo tags from
        # that member, while Ban and Open both read links[0]. With a tweet first, a
        # card wearing a GitHub badge banned the TWEET url — a junk row in
        # `banned_repos`, the repo still live, `kept` still set, and the card gone
        # from the screen, so the user believed the ban had worked.
        ordered = sorted(idxs, key=lambda i: survivors[i] is not rep)
        topics.append({"title": g["title"] or survivors[idxs[0]].title,
                       "why": g["why"],
                       "score": max(scores[i] for i in idxs),
                       "links": [survivors[i].url for i in ordered],
                       "source": _cluster_source([survivors[i] for i in idxs]),
                       **_repo_meta(rep)})
    for i in range(n):
        if i in used or i in stale:
            continue
        topics.append({"title": titles[i] or survivors[i].title,
                       "why": reasons[i] or survivors[i].description or "",
                       "score": scores[i],
                       "links": [survivors[i].url],
                       "source": _source_key(survivors[i]),
                       **_repo_meta(survivors[i])})
    return topics


def _repo_meta(sig: "Signal") -> dict:
    """Card-facing repo metadata carried onto a topic: stars + creation date +
    last-modified (pushed_at, kept in `date`). Non-GitHub signals (tweets) have no
    stars/created, so those come back None and the UI just omits the meta row."""
    return {"stars": sig.stars, "created": sig.created, "updated": sig.date,
            "topics": list(getattr(sig, "topics", None) or [])}


# The weak model output-fatigues and silently OMITS signals from a long scoring
# reply, so a batch can come back covering fewer signals than it was sent. Re-ask
# the omitted ones (in a smaller batch, which fatigues less) up to this many times
# before giving up — the scoring-side equivalent of the grouping coverage guard.
_GAP_FILL_RETRIES = 2


def _score_pass(pairs: list[tuple[int, "Signal"]], recent_titles: list[str],
                client, system_prompt: str | None, batch_size: int,
                cancel_event=None) -> tuple[dict[int, dict], int]:
    """Score (global_index, signal) pairs in batches of `batch_size`. Returns
    ({global_index: {"score","reason","title"}}, failed_batches) for the signals the
    model returned (omitted ones are simply absent, to be re-asked by the caller).
    Swallowing a dead batch keeps the run alive, but the count has to come back with
    it: with EVERY batch failing nothing is scored, nothing survives, and the feed is
    empty for a reason no one can see. Checks `cancel_event` before each batch so Stop
    bites during the LLM phase."""
    out: dict[int, dict] = {}
    failed = 0
    for start in range(0, len(pairs), batch_size):
        if cancel_event is not None and cancel_event.is_set():
            raise RunCancelled()
        chunk = pairs[start:start + batch_size]
        gidx = [gi for gi, _ in chunk]
        batch = [s for _, s in chunk]
        # A dead batch must not take the run with it. This was the LAST unguarded
        # call and by far the most expensive one: every batch already paid for, plus
        # ~15 minutes of scraping, is lost if one reply comes back truncated (a
        # 120-signal batch meeting the output-token ceiling stops mid-JSON) — and
        # nothing is persisted until `rank` returns. Its signals simply stay unscored,
        # which is the same state the model's own omissions leave them in, so the
        # gap-fill above re-asks them in a smaller batch.
        try:
            raw = client.make(build_messages(batch, recent_titles, system_prompt))
            scored = parse_scored(raw)
        except RunCancelled:
            raise                       # Stop is not a failure — it must still get out
        except Exception:
            failed += 1
            continue
        for s in scored:
            if 0 <= s["i"] < len(gidx):
                out[gidx[s["i"]]] = {"score": s["score"], "reason": s["reason"],
                                     "title": s["title"]}
    return out, failed


def _script_of(text: str) -> tuple[int, int]:
    """(latin letters, cyrillic letters) — enough to tell which script a sentence is
    written in without dragging in a language-detection dependency."""
    return (len(re.findall(r"[A-Za-z]{2,}", text)),
            len(_CYRILLIC.findall(text)))


def _looks_foreign(text: str, script: str = "cyrillic") -> bool:
    """Did this description come back in the wrong script?

    Asymmetric on purpose. For a CYRILLIC target the failure is common and obvious
    (the model echoes an English source), so: no Cyrillic at all plus enough Latin
    words to be a sentence. For a LATIN target the same test would flag every
    correct description, and the real failure — a whole sentence in another script —
    is rare, so it must be MOSTLY non-Latin before we pay to rewrite it. A product
    name in another alphabet inside an English sentence is not drift.

    The word floor keeps the repair off stubs and name-only descriptions either way,
    where a rewrite buys nothing and the 'language' of one token is undefined."""
    if not text:
        return False
    latin, cyr = _script_of(text)
    if script == "cyrillic":
        return cyr == 0 and latin >= 3
    return cyr >= 3 and cyr > latin


def fix_reason_language(scored: list[dict], client, key: str = "reason",
                        lang: str | None = None) -> list[dict]:
    """Re-ask for any `reason` that came back in the wrong language.

    The prompt already demands the INTERFACE language and usually gets it (the
    target comes from the catalogue, not from a language named here), but a long scoring
    reply occasionally flips language for the WHOLE batch: one live run returned 33
    of 71 descriptions in English, all from a single batch of 120, while three
    offline replays of the same tweets returned none. A prompt edit cannot be shown
    to fix per-batch roulette, so the guarantee is made here instead.

    Costs one small call only on a run that actually drifted. Crash-proof, exactly
    like the dedup and gate passes: any failure leaves every reason untouched, and a
    replacement that is STILL in the wrong script is refused rather than trusted. `title`
    is never sent — it is required to be English."""
    from topicparser import i18n
    strings = i18n.strings(lang)
    language = strings.get("lang.name", "English")
    script = strings.get("lang.script", "latin")

    bad = {i: r[key] for i, r in enumerate(scored)
           if _looks_foreign(r.get(key) or "", script)}
    if not bad:
        return scored
    try:
        raw = client.make([
            {"role": "system", "content": _relang_system(language)},
            {"role": "user", "content": json.dumps(
                {str(i): t for i, t in bad.items()}, ensure_ascii=False)},
        ])
    except RunCancelled:
        raise
    except Exception:
        return scored
    try:
        fixed = (json.loads(raw) or {}).get("fixed") or {}
    except Exception:
        return scored
    if not isinstance(fixed, dict):
        return scored
    for idx, text in fixed.items():
        try:
            i = int(idx)
        except (TypeError, ValueError):
            continue
        # only accept a replacement that actually IS in the target language
        if (i in bad and isinstance(text, str) and text.strip()
                and not _looks_foreign(text, script)):
            scored[i][key] = text.strip()
    return scored


def _no_drops() -> dict:
    """The empty drop record. Always present in `rank`'s result, so a reader never
    has to tell "the gate was off" apart from "the gate dropped nothing"."""
    return {"xgate": [], "feedgate": [], "dedup": []}


def rank(signals: list[Signal], recent_titles: list[str], client,
         system_prompt: str | None = None, batch_size: int = 120,
         keep: int = 70, group_prompt: str | None = None,
         dedup_prompt: str | None = None, xgate_prompt: str | None = None,
         feedgate_prompt: str | None = None,
         cancel_event=None, lang: str | None = None) -> dict:
    """PASS 1 scores every signal with the profile prompt (batched on big days),
    re-asking any the model omits so none is dropped without a score — survivors
    >= `keep` also carry a per-signal English title. PASS 2 asks the grouping
    prompt ONLY for same-story clusters (+ stale indices); the final topic list is
    assembled in code, so no survivor can be silently dropped."""
    if not signals:
        return {"topics": [], "scored": [], "raw": "", "dropped": _no_drops(),
                "failed_batches": 0, "unscored": 0}

    # PASS 1 — score everything, then gap-fill whatever the model skipped. Each
    # retry re-asks only the omitted signals; a smaller reply fatigues less, so it
    # converges. Stop early if a whole pass returns nothing (the model won't score
    # these) — don't burn identical retries.
    scored_by_i: dict[int, dict] = {}
    failed_batches = 0
    pending = list(enumerate(signals))
    for _ in range(_GAP_FILL_RETRIES + 1):
        if not pending:
            break
        got, failed = _score_pass(pending, recent_titles, client, system_prompt,
                                  batch_size, cancel_event=cancel_event)
        failed_batches += failed
        if not got:
            break
        scored_by_i.update(got)
        pending = [(gi, s) for gi, s in pending if gi not in scored_by_i]
    # Signals the gap-fill gave up on, for ANY reason — a SUPERSET of what the dead
    # batches took with them, not the other half of it. Read the pair: both non-zero
    # means calls were failing; `unscored` alone means a reply that parsed and simply
    # left signals out. Either way they are the null scores in the log.
    unscored = len(pending)

    # What each gate threw away, for the debug log. A run costs money and fifteen
    # minutes; when eight tweets about one release produce no topic, the log has to
    # say WHICH pass removed them instead of leaving the next session to guess.
    dropped = _no_drops()
    scored_all = []
    survivors, surv_scores, surv_titles, surv_reasons = [], [], [], []
    for gi, sig in enumerate(signals):
        s = scored_by_i.get(gi)
        if s is None:
            continue
        scored_all.append({"i": gi, "score": s["score"], "reason": s["reason"]})
        if s["score"] >= keep:
            survivors.append(sig)
            surv_scores.append(s["score"])
            surv_titles.append(s["title"])
            surv_reasons.append(s["reason"])
    if not survivors:
        return {"topics": [], "scored": scored_all, "raw": "", "dropped": dropped,
                "no_prompt": not system_prompt,
                "failed_batches": failed_batches, "unscored": unscored}

    # PASS 2 — X gate: re-judge the surviving TWEETS on the one question the big
    # score call never reaches (did the author already say it all?). Opt-in: with no
    # prompt wired there is no extra call. Runs BEFORE clustering so a gated tweet
    # cannot pull a cluster together either.
    # The official-source gate is the same shape, one source over: it asks whether the
    # post IS the event or the lab talking about itself. Both gates cut before
    # clustering, so a gated post cannot pull a cluster together either.
    if xgate_prompt or feedgate_prompt:
        gated = set()
        if xgate_prompt:
            cut = gate_tweets(survivors, client, xgate_prompt, cancel_event)
            dropped["xgate"] = [survivors[i].url for i in sorted(cut)]
            gated |= cut
        if feedgate_prompt:
            cut = gate_feeds(survivors, client, feedgate_prompt, cancel_event)
            dropped["feedgate"] = [survivors[i].url for i in sorted(cut)]
            gated |= cut
        if gated:
            keepers = [i for i in range(len(survivors)) if i not in gated]
            survivors = [survivors[i] for i in keepers]
            surv_scores = [surv_scores[i] for i in keepers]
            surv_titles = [surv_titles[i] for i in keepers]
            surv_reasons = [surv_reasons[i] for i in keepers]
            if not survivors:
                return {"topics": [], "scored": scored_all, "raw": "",
                        "no_prompt": not system_prompt,
                        "failed_batches": failed_batches, "unscored": unscored,
                        "dropped": dropped}

    if cancel_event is not None and cancel_event.is_set():
        raise RunCancelled()
    # A dead clustering call (rate limit, network blip) must degrade to all-singletons,
    # NOT lose the run: by this point the scrape and every scoring call are already paid
    # for and nothing has been persisted yet. `parse_groups` already treats a broken
    # reply that way; an exception now gets the same treatment.
    try:
        raw2 = client.make(build_group_messages(survivors, surv_scores,
                                                recent_titles, group_prompt))
    except RunCancelled:
        raise
    except Exception:
        raw2 = ""
    topics = _assemble_topics(survivors, surv_scores, surv_titles,
                              surv_reasons, parse_groups(raw2))
    # PASS 3 — cross-run dedup: drop any assembled topic whose story was already
    # shown in a prior run. Separate focused call; skipped when nothing was shown.
    before = topics
    topics = dedup_shown(topics, recent_titles, client, dedup_prompt, cancel_event)
    # `dedup_shown` returns the SAME dict objects it kept, so identity names the rest
    kept_ids = {id(t) for t in topics}
    dropped["dedup"] = [t["title"] for t in before if id(t) not in kept_ids]
    # LAST — repair any description that came back in the wrong language. Done here,
    # on the final list, so it covers cluster `why` (written by the grouping call) as
    # well as singleton reasons, and pays for the fewest items possible.
    fix_reason_language(topics, client, key="why", lang=lang)
    return {"topics": topics, "scored": scored_all, "raw": raw2, "dropped": dropped,
            # NO prompt at all is the same disaster as an EMPTY one, and it used to be
            # the silent half: the caller simply passes None, the scoring falls back to
            # DEFAULT_SYSTEM, and both gates are skipped for want of a prompt file. The
            # flag travels with the result so the caller cannot forget to ask.
            "no_prompt": not system_prompt,
            "failed_batches": failed_batches, "unscored": unscored}
