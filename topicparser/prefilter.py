import re
from datetime import datetime, timezone, timedelta
from topicparser.models import Signal

def _parse(dt: str):
    """ISO timestamp -> aware datetime, or None when unparseable. A string carrying
    no offset is read as UTC: comparing it to an aware `now` would otherwise raise
    ("can't subtract offset-naive and offset-aware datetimes") and take the whole
    run down over one odd field. Both live sources send `Z`, so this is a guard,
    not a behaviour change."""
    try:
        d = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    except Exception:
        return None
    return d if d.tzinfo is not None else d.replace(tzinfo=timezone.utc)

def filter_fresh(signals: list[Signal], *, gh_days: int, x_days: int,
                 feed_days: int | None = None) -> list[Signal]:
    """Each source ages differently. A repo pushed six weeks ago is still a find; a
    tweet from last week is not; an official post is news for about a week. `feed_days`
    defaults to the X window rather than the GitHub one — a month-old blog post is not
    what this source is for."""
    now = datetime.now(timezone.utc)
    windows = {"x": x_days, "feed": x_days if feed_days is None else feed_days}
    out = []
    for s in signals:
        window = windows.get(s.source, gh_days)
        d = _parse(s.date)
        if d is None:                       # unknown date -> keep (safe fallback)
            out.append(s); continue
        if now - d <= timedelta(days=window):
            out.append(s)
    return out

def drop_seen_links(signals: list[Signal], seen: set[str]) -> list[Signal]:
    return [s for s in signals if s.url not in seen]

# How much of the description still counts as "this signal is ABOUT the subject".
# Past that, a hit is a passing mention in a list of supported models.
_LEAD_CHARS = 60


# A term is a WORD, and the separators are the ones a repo name actually uses: it is
# `owner/repo`, so `-`, `/`, `_` and `.` all divide words there. Matching on the raw
# string let a term eat every longer word containing it (`grok` dropped
# `grokking-algorithms`); requiring whitespace instead would let `ai-agents` slip past
# the term `agents`, which only moves the error to the other side.
_SEP = r"[^A-Za-z0-9]"


def _term_re(term: str):
    return re.compile(rf"(?:^|{_SEP})" + re.escape(term) + rf"(?:{_SEP}|$)")


def _norm(s: str) -> str:
    """Every run of non-alphanumerics becomes one space: `owner/stable-diffusion-webui`
    -> `owner stable diffusion webui`. Used ONLY for a term that contains a space."""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _phrase_re(term: str):
    return re.compile(r"(?:^| )" + re.escape(_norm(term)) + r"(?: |$)")


def _is_about(sig: Signal, term: str) -> bool:
    """The subject leads: it is in the name, or opens the description.

    Deliberately NOT a plain substring search over the whole text. Half the signals
    naming a given model are multi-model tools ("use any LLM: Claude, Gemini, Grok,
    Ollama") that are not about it at all, and dropping those loses real topics.

    A term with a SPACE gets a second, separate path. The word matcher splits on the
    separators a repo name uses, so `stable diffusion` matched the prose form and
    missed `stable-diffusion-webui` — i.e. it worked on the source with the fewest
    signals and was silent on GitHub, where names are hyphenated almost always, and
    the reader saw it fire on a blog and concluded the filter was live.

    Why not normalise both sides always: normalising collapses punctuation, so `c++`
    degrades to `c` and starts dropping `c-compiler` and `objective-c`. Splitting the
    paths makes that impossible rather than unlikely."""
    pattern = _term_re(term)
    lead = (sig.description or "").lower()[:_LEAD_CHARS]
    if pattern.search((sig.title or "").lower()) or pattern.search(lead):
        return True
    if " " not in term.strip():
        return False
    phrase = _phrase_re(term)
    return bool(phrase.search(_norm(sig.title)) or phrase.search(_norm(lead)))


def drop_off_interest(signals: list[Signal], terms: set[str],
                      dropped=None) -> list[Signal]:
    """Drop signals whose SUBJECT is something the owner does not cover.

    Runs before scoring, so an off-interest signal costs no LLM call and cannot be
    rescued by a model having a bad day. The prompt-level cap in `_base.txt` stays —
    it catches the softer cases; this catches the ones that leak.

    `dropped` receives the title of each signal removed, for the run log. Every gate
    downstream records what it threw away; this one dropped signals BEFORE any of that
    and left only a smaller `after_prefilter` behind, so a term that matched more than
    the reader meant was invisible to the person who typed it."""
    if not terms:
        return signals
    if dropped is not None:
        for s in signals:
            if any(_is_about(s, t) for t in terms):
                dropped(s.title)
    return [s for s in signals
            if not any(_is_about(s, t) for t in terms)]


def drop_banned(signals: list[Signal], banned: set[str]) -> list[Signal]:
    """Drop GitHub signals whose repo (== title, owner/repo) the user banned.
    Runs before scoring so a banned repo never costs an LLM call and never returns."""
    if not banned:
        return signals
    # lowercased on both sides: GitHub is case-insensitive about `owner/repo`, so a
    # ban typed with different capitals used to sail past this and reach the feed again
    low = {b.lower() for b in banned}
    return [s for s in signals
            if not (s.source == "github" and (s.title or "").lower() in low)]
