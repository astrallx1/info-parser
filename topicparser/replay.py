"""Re-score a past run's signals with a candidate prompt.

Tuning used to cost a whole run: ~15 minutes of scraping plus every paid call, and
then you still had to read a JSON dump to see what changed. But every run already
writes its raw signals to `debug/`, so a prompt edit can be checked against the exact
same input in ONE call. This is the offline-replay method the project has always used
for tuning, made available from the app.

Two honest limits, both worth repeating wherever this is surfaced:
  * the debug log does NOT store per-signal `stars`, so any rule that keys on traction
    cannot be reproduced here;
  * a score at this model tier is a function of the WHOLE batch, so a capped sample
    answers "did my rule fire", not "this is exactly what the next run will show".
"""
import glob
import json
import os

from topicparser.models import Signal
from topicparser.ranker import build_messages, parse_scored

DEFAULT_LIMIT = 120        # one production batch: enough to be representative, one call


def latest_debug_run(debug_dir: str) -> str | None:
    runs = sorted(glob.glob(os.path.join(debug_dir or "", "run-*.json")))
    return runs[-1] if runs else None


def load_signals(path: str, profile: str) -> tuple[list[Signal], list[int]]:
    """Rebuild (signals, their scores in that run) from a debug log.

    Falls back to whatever profile the log holds when the requested one is absent —
    testing a new profile's prompt against another profile's signals is far more
    useful than refusing to test at all."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    profiles = data.get("profiles") or {}
    block = profiles.get(profile)
    if block is None:
        block = next(iter(profiles.values()), {})
    rows = block.get("scored") or []

    signals, before = [], []
    for r in rows:
        signals.append(Signal.make(source=r.get("source") or "", title=r.get("title") or "",
                                   description=r.get("text") or "", url=r.get("url") or "",
                                   date=r.get("date") or "", profile=profile))
        before.append(r.get("score"))
    return signals, before


def score_with(path: str, profile: str, prompt: str, client, *, threshold: int = 70,
               limit: int = DEFAULT_LIMIT) -> dict:
    """Score a capped sample with `prompt` and report it beside the original scores."""
    signals, before = load_signals(path, profile)
    total = len(signals)
    signals, before = signals[:limit], before[:limit]

    scored: dict[int, dict] = {}
    if signals:
        try:
            raw = client.make(build_messages(signals, [], prompt))
            for s in parse_scored(raw):
                if 0 <= s["i"] < len(signals):
                    scored[s["i"]] = s
        except Exception:
            scored = {}      # a failed test must report nothing, never a wrong verdict

    rows = []
    for i, sig in enumerate(signals):
        hit = scored.get(i)
        rows.append({
            "title": sig.title, "url": sig.url, "source": sig.source,
            "text": sig.description[:220],
            "before": before[i],
            "after": hit["score"] if hit else None,
            "reason": (hit or {}).get("reason") or "",
            "new_title": (hit or {}).get("title") or "",
        })
    # unscored last: they carry no verdict, and burying them keeps the useful rows on top
    rows.sort(key=lambda r: (r["after"] is None, -(r["after"] or 0)))

    return {
        "ok": True,
        "run": os.path.basename(path),
        "profile": profile,
        "tested": len(signals),
        "total_available": total,
        "threshold": threshold,
        "passed": sum(1 for r in rows if (r["after"] or 0) >= threshold),
        "before_passed": sum(1 for r in rows if (r["before"] or 0) >= threshold),
        "skipped": sum(1 for r in rows if r["after"] is None),
        "rows": rows,
    }
