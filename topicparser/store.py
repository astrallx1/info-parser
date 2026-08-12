import json, os, threading
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy import Integer, Text, create_engine, event, func, select, delete
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from dotenv import load_dotenv
from topicparser import paths

load_dotenv(paths.resolve(".env"))
# main.py overrides this; the default is anchored to the app so a packaged run
# never opens a fresh empty database in whatever folder it happened to start in
DB_PATH = paths.resolve(os.environ.get("DB_PATH", "./topics.db"))
_lock = threading.Lock()
_engine = None
_Session = None

class Base(DeclarativeBase): pass

class Topic(Base):
    __tablename__ = "shown_topics"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text)
    why: Mapped[str] = mapped_column(Text)
    links: Mapped[str] = mapped_column(Text)          # JSON array
    # written on every insert, read by nothing: it predates the dedup call, which
    # compares TITLES. Left in place because dropping a column costs a migration and
    # buys nothing — do not go looking for the consumer, there isn't one.
    signature: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[int] = mapped_column(Integer, default=0)
    profile: Mapped[str] = mapped_column(Text, default="")
    # 'gh' / 'tw' / 'feed' / 'pod' / 'other', decided ONCE in the ranker from the signal
    # that produced the topic. NULL on rows written before the column existed, and the
    # feed and the export both fall back to sniffing links[0] for those.
    source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # The card's repo band as JSON: stars, velocity, created, updated, the repo's own
    # GitHub tags. ONE column rather than five because nothing queries these — they are
    # carried, not searched — and `ranker._repo_meta` is the only thing that writes the
    # shape. Without it the `.md` printed no traction at all: the export is assembled
    # from the DB, so a number that never reached a row never reached the file either.
    meta: Mapped[Optional[str]] = mapped_column(Text, nullable=True)     # JSON object
    # Which RUN wrote this row — the app's own timestamp, taken once per run. It is
    # what lets the feed come back after a restart: the screen's scope is the last
    # run, and `last_shown` cannot express that (every row carries its own instant).
    # NULL on rows written before the column existed, and those are never treated as
    # a run, or every old topic would read as one.
    run_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kept: Mapped[int] = mapped_column(Integer, default=1)
    first_shown: Mapped[str] = mapped_column(Text)
    last_shown: Mapped[str] = mapped_column(Text)

class TrackedRepo(Base):
    __tablename__ = "tracked_repos"
    repo: Mapped[str] = mapped_column(Text, primary_key=True)
    added: Mapped[str] = mapped_column(Text)
    last_growing: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

class StarHistory(Base):
    __tablename__ = "star_history"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repo: Mapped[str] = mapped_column(Text)
    stars: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[str] = mapped_column(Text)

class BannedRepo(Base):
    __tablename__ = "banned_repos"
    repo: Mapped[str] = mapped_column(Text, primary_key=True)   # owner/repo
    banned_at: Mapped[str] = mapped_column(Text)

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _enable_wal(conn, _r):
    cur = conn.cursor(); cur.execute("PRAGMA journal_mode=WAL"); cur.close()

def _build_engine(path):
    global _engine, _Session
    if _engine is not None: _engine.dispose()
    _engine = create_engine(f"sqlite:///{path}", future=True,
                            connect_args={"check_same_thread": False})
    event.listen(_engine, "connect", _enable_wal)
    _Session = sessionmaker(bind=_engine, future=True)

def _session():
    if _Session is None: _build_engine(DB_PATH)
    return _Session()

def _migrate(engine):
    """create_all() adds missing TABLES but never missing COLUMNS. Older DBs have
    tables from an earlier schema; add any columns the models gained since. Idempotent."""
    wanted = {
        "tracked_repos": [("description", "TEXT"), ("last_growing", "TEXT")],
        "shown_topics": [("signature", "TEXT DEFAULT ''"), ("score", "INTEGER DEFAULT 0"),
                         ("profile", "TEXT DEFAULT ''"), ("kept", "INTEGER DEFAULT 1"),
                         ("source", "TEXT"), ("run_id", "TEXT"), ("meta", "TEXT")],
    }
    # Every velocity reads one repo's whole history, and detect_trending does that once
    # per tracked repo, so an unindexed star_history is a full scan per repo — it was
    # bounded by a LIMIT 2 until the trending fix. HERE and not `index=True` on the
    # model: create_all skips a table that already exists, so a DB in the field would
    # never gain it.
    indexes = [("ix_star_history_repo", "star_history", "repo")]
    with engine.begin() as conn:
        for table, cols in wanted.items():
            info = list(conn.exec_driver_sql(f"PRAGMA table_info({table})"))
            if not info:
                continue                      # table doesn't exist yet -> create_all handled it
            have = {r[1] for r in info}
            for name, decl in cols:
                if name not in have:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        for name, table, col in indexes:
            conn.exec_driver_sql(
                f"CREATE INDEX IF NOT EXISTS {name} ON {table}({col})")


def init_db():
    with _lock:
        _build_engine(DB_PATH)
        Base.metadata.create_all(_engine)
        _migrate(_engine)

def checkpoint():
    """Merge the WAL back into the main db file so `topics.db` alone is current.
    In WAL mode recent writes live in the `-wal` sidecar until a checkpoint; without
    this, copying/backing-up `topics.db` by itself (Time Machine, `cp`, a move to
    another machine) loses every write since the last auto-checkpoint. Best-effort —
    a checkpoint failure must never break a run. Uses a raw autocommit connection
    (wal_checkpoint can't run inside a transaction)."""
    if _engine is None:
        return
    try:
        with _lock:
            raw = _engine.raw_connection()
            try:
                cur = raw.cursor()
                cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                cur.close()
            finally:
                raw.close()
    except Exception:
        pass

def close():
    """Checkpoint then dispose the engine on app shutdown, leaving `topics.db` as the
    single source of truth (no orphaned `-wal`). The store rebuilds lazily if used
    again, so calling this is safe even mid-session."""
    global _engine, _Session
    checkpoint()
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = _Session = None

def count_all() -> dict:
    """What a reset would remove. Shown in the confirmation, so the number is the
    user's own data and not an abstract warning."""
    with _lock, _session() as s:
        return {"topics": s.query(Topic).count(),
                "tracked": s.query(TrackedRepo).count(),
                "stars": s.query(StarHistory).count(),
                "banned": s.query(BannedRepo).count()}


def reset_all(topics: bool = True, tracked: bool = True, banned: bool = True) -> str | None:
    """Empty the chosen tables, after copying the file aside. Returns the backup path,
    or None when nothing was selected.

    The most destructive thing the app can do, so it is a per-part choice: shown topics
    (clearing them restarts cross-run dedup), the watchlist together with the star
    history trending is derived from, and the ban list. `tracked` takes `star_history`
    with it on purpose — a tracked repo with no history can never show a velocity.

    It empties rather than deletes, so the schema survives and the next run needs no
    setup, and it CHECKPOINTS first, or the backup would miss every write still sitting
    in the `-wal` sidecar.
    """
    import shutil

    wanted = [m for m, on in ((StarHistory, tracked), (TrackedRepo, tracked),
                              (Topic, topics), (BannedRepo, banned)) if on]
    if not wanted:
        return None
    checkpoint()
    backup = None
    if os.path.exists(DB_PATH):
        # One fixed name meant the second wipe ate the first wipe's backup — and the
        # first is sometimes the only copy of something. Two wipes inside one second
        # would collide on the stamp alone, so the counter closes that too.
        stem = f"{DB_PATH}.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        backup, n = stem, 1
        while os.path.exists(backup):
            backup, n = f"{stem}-{n}", n + 1
        shutil.copy2(DB_PATH, backup)
    with _lock, _session() as s:
        for model in wanted:
            s.query(model).delete()
        s.commit()
    checkpoint()
    return backup


# What `_topic_dict` splats back out of the `meta` column, and the only keys it takes
# from it: a stored blob cannot be allowed to overwrite `id` or `title` on the way back.
META_KEYS = ("stars", "velocity", "created", "updated", "topics")


def insert_topic(*, title, why, links, signature, score, profile, source=None,
                 run_id=None, meta=None) -> int:
    now = _now()
    kept_meta = {k: v for k, v in (meta or {}).items() if k in META_KEYS}
    with _lock, _session() as s:
        t = Topic(title=title, why=why, links=json.dumps(links), signature=signature,
                  score=score, profile=profile, source=source, kept=1,
                  meta=json.dumps(kept_meta) if kept_meta else None,
                  run_id=run_id, first_shown=now, last_shown=now)
        s.add(t); s.commit(); return t.id


def _topic_dict(r) -> dict:
    """The row as the feed and the export read it. `meta` is splatted back to the flat
    keys both of them already expect, so a restored card and a fresh one have the same
    shape — anything missing (a tweet, a row written before the column) reads as None
    rather than 0, which is what makes the export OMIT the line instead of lying."""
    try:
        meta = json.loads(r.meta) if r.meta else {}
    except Exception:
        meta = {}
    return {"id": r.id, "title": r.title, "why": r.why,
            "links": json.loads(r.links), "signature": r.signature,
            "score": r.score, "profile": r.profile, "source": r.source,
            "run_id": r.run_id, "kept": r.kept,
            "stars": meta.get("stars"), "velocity": meta.get("velocity"),
            "created": meta.get("created"), "updated": meta.get("updated"),
            "topics": meta.get("topics") or []}


def get_last_run_topics() -> list[dict]:
    """Every topic the most recent run produced, newest run first — the scope the feed
    draws and the scope one `.md` covers. Rows with no `run_id` predate the column and
    are skipped: lumping them together would make every old topic one enormous run."""
    with _lock, _session() as s:
        latest = s.execute(select(func.max(Topic.run_id))).scalar()
        if not latest:
            return []
        rows = s.execute(select(Topic).where(Topic.run_id == latest)
                         .order_by(Topic.score.desc())).scalars().all()
        return [_topic_dict(r) for r in rows]

def get_recent_topics(days: int) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _lock, _session() as s:
        rows = s.execute(select(Topic).where(Topic.last_shown >= cutoff)
                         .order_by(Topic.last_shown.desc())).scalars().all()
        return [_topic_dict(r) for r in rows]

def seen_links(days: int) -> set[str]:
    out: set[str] = set()
    for t in get_recent_topics(days):
        out.update(t["links"])
    return out

def _topic_window(links_json: str, source: str | None = None) -> str:
    """Which freshness window this topic expires on: 'tw', 'feed' or 'gh'.

    The stored `source` answers it outright. Sniffing links[0] is the fallback for rows
    written before that column existed — and it was wrong for a cluster whose first link
    happened to be the tweet next to a repo, which handed a GitHub topic X's five-day
    expiry. **That fallback can only recognise X:** a blog URL is indistinguishable
    from any other link, so a legacy FEED row keeps the GitHub window rather than a
    guess. Three-position for everything written since the column exists, two-position
    for what came before it."""
    # A podcast IS a feed post — the split is about who is speaking, not about how long
    # the topic stays fresh — so `pod` answers the feed window. It fell through to
    # 'gh' here for a day: harmless only while GH_FRESH_DAYS is the widest of the
    # three, and the moment it is narrowed the row is deleted early, leaves `seen_links`
    # with it, and the episode comes back as new.
    if source:
        return source if source in ("tw", "feed") else ("feed" if source == "pod"
                                                        else "gh")
    try:
        links = json.loads(links_json)
    except Exception:
        return "gh"
    first = (links[0] if links else "").lower()
    return "tw" if ("x.com" in first or "twitter.com" in first) else "gh"

def cleanup_topics(x_days: int, gh_days: int, feed_days: int | None = None):
    """Drop topics past their source's window. `feed_days` defaults to the X one, the
    same fallback `prefilter.by_freshness` uses — the two defaulted differently, which
    is the shape of the bug they were both written against: a feed topic got the GitHub
    window here, so a blog post shown 20 days ago was deleted at `GH_FRESH_DAYS`=14,
    fell out of `seen_links` with it, and was collected, scored and shown again. The
    cleanup and the freshness filter have to answer the same question the same way."""
    now = datetime.now(timezone.utc)
    cuts = {"tw": (now - timedelta(days=x_days)).isoformat(),
            "gh": (now - timedelta(days=gh_days)).isoformat(),
            "feed": (now - timedelta(days=feed_days if feed_days is not None
                                     else x_days)).isoformat()}
    with _lock, _session() as s:
        for t in s.execute(select(Topic)).scalars().all():
            if t.last_shown < cuts[_topic_window(t.links, t.source)]:
                s.delete(t)
        s.commit()

def set_kept(topic_id: int, kept: bool):
    with _lock, _session() as s:
        t = s.get(Topic, topic_id)
        if t: t.kept = 1 if kept else 0; s.commit()

def _backdate_topic(topic_id: int, days: int):        # test helper
    old = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _lock, _session() as s:
        t = s.get(Topic, topic_id)
        t.first_shown = old; t.last_shown = old; s.commit()

from sqlalchemy import desc

def add_tracked_repo(repo: str, description: str | None = None):
    with _lock, _session() as s:
        tr = s.get(TrackedRepo, repo)
        if not tr:
            s.add(TrackedRepo(repo=repo, added=_now(), last_growing=_now(),
                              description=description)); s.commit()
        elif description and tr.description != description:
            tr.description = description; s.commit()   # backfill on re-watch

def get_tracked_repos() -> list[str]:
    with _lock, _session() as s:
        return list(s.execute(select(TrackedRepo.repo)).scalars().all())

def record_stars(repo: str, stars: int, at: str | None = None):
    ts = at or _now()
    with _lock, _session() as s:
        prev = s.execute(select(StarHistory.stars).where(StarHistory.repo == repo)
                         .order_by(desc(StarHistory.timestamp)).limit(1)).scalar_one_or_none()
        s.add(StarHistory(repo=repo, stars=stars, timestamp=ts))
        if prev is not None and stars > prev:      # it grew -> not stagnant
            tr = s.get(TrackedRepo, repo)
            if tr:
                tr.last_growing = ts
        s.commit()


def drop_stagnant_repos(days: int) -> list[str]:
    """Remove tracked repos that have not grown in `days` (velocity ~0 too long).
    `last_growing` is set at add-time and bumped on every star increase, so a repo
    whose last_growing is older than the window is stagnant. Returns removed repos."""
    cut = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _lock, _session() as s:
        stale = [tr.repo for tr in s.execute(select(TrackedRepo)).scalars().all()
                 if (tr.last_growing or tr.added) < cut]
        for repo in stale:
            s.execute(delete(StarHistory).where(StarHistory.repo == repo))
            s.execute(delete(TrackedRepo).where(TrackedRepo.repo == repo))
        s.commit()
    return stale


def _set_last_growing(repo: str, days_ago: int):        # test helper
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    with _lock, _session() as s:
        tr = s.get(TrackedRepo, repo)
        tr.last_growing = ts; s.commit()

def _history(repo: str):
    """Every snapshot of one repo, newest first. Bounded by `prune_star_history`."""
    with _lock, _session() as s:
        return s.execute(select(StarHistory).where(StarHistory.repo == repo)
                         .order_by(desc(StarHistory.timestamp))).scalars().all()

def velocity(repo: str, min_hours: float = 12):
    # shown in the tracked table — same measurement as detect_trending, same guard
    return _velocity_from(_history(repo), 0, min_hours)[0]

def _velocity_from(rows, i, min_hours=0.0):
    """Velocity (Δstars/Δdays) between snapshot `i` of `rows` (newest first) and the
    newest snapshot at least `min_hours` OLDER. Returns (rate, index of that snapshot),
    or (None, None) when no snapshot is old enough.

    The floor is there because a real gain over a tiny interval extrapolates to an
    absurd stars/day (two runs 3h apart turned +400 stars into 3200/day). It used to be
    applied to the pair i / i+1 and then give up — so ONE extra run 2h after a breakout
    made the newest pair too short, answered None, and the older snapshots that measure
    it perfectly well were never looked at. Anyone running the parser twice a day saw no
    velocity in the tracked table and no breakout alert, ever. Skip the short interval,
    do not abandon the repo."""
    if i is None or i >= len(rows):
        return None, None
    d0 = datetime.fromisoformat(rows[i].timestamp)
    for j in range(i + 1, len(rows)):
        days = (d0 - datetime.fromisoformat(rows[j].timestamp)).total_seconds() / 86400
        if days > 0 and days * 24 >= min_hours:
            return (rows[i].stars - rows[j].stars) / days, j
    return None, None


def detect_trending(min_velocity: float, min_hours: float = 12) -> list[dict]:
    """Breakout channel — SEPARATE from the topic pipeline (bypasses dedup). A tracked
    repo alerts on the cold->hot TRANSITION: current velocity >= min AND the previous
    velocity was below min (or absent). Stays silent while it remains hot; can re-alert
    after it cools. Purely derived from star_history — no persisted 'alerted' flag.
    `min_hours` guards against short intervals: two runs closer than this produce an
    extrapolated (inflated) stars/day, so the measurement REACHES BACK to the newest
    snapshot old enough to trust rather than giving up on the repo. `prev` is measured
    from where the current window ends, by the same rule."""
    out = []
    with _lock, _session() as s:
        for tr in s.execute(select(TrackedRepo)).scalars().all():
            rows = s.execute(select(StarHistory).where(StarHistory.repo == tr.repo)
                             .order_by(desc(StarHistory.timestamp))).scalars().all()
            # `prev` is measured from where `cur`'s window ENDS, by the same rule.
            # Anchored on the next ROW instead, it reaches back over an interval that
            # OVERLAPS the breakout, reads as "it was already hot", and swallows the
            # alert. Measured, not reasoned: that half-fix fails three tests here.
            cur, older = _velocity_from(rows, 0, min_hours)
            prev, _ = _velocity_from(rows, older, min_hours)
            hot_now = cur is not None and cur >= min_velocity
            hot_before = prev is not None and prev >= min_velocity
            if hot_now and not hot_before:
                out.append({"repo": tr.repo, "url": f"https://github.com/{tr.repo}",
                            "stars": rows[0].stars, "velocity": cur,
                            "description": tr.description})
    return out


# How long a repo's star snapshots are kept. NOT `GH_FRESH_DAYS`, which it used to be:
# that knob decides how old a GitHub SIGNAL may be, and one number quietly doing two
# unrelated jobs meant narrowing the freshness window also blinded `detect_trending`,
# which needs a pair of snapshots at least 12 h apart to say anything at all. Off the
# Settings screen on purpose — nobody should tune retention from a form.
STAR_HISTORY_DAYS = 90


def prune_star_history(days: int):
    cut = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _lock, _session() as s:
        s.execute(delete(StarHistory).where(StarHistory.timestamp < cut)); s.commit()

def remove_tracked_repo(repo: str):
    with _lock, _session() as s:
        s.execute(delete(StarHistory).where(StarHistory.repo == repo))
        s.execute(delete(TrackedRepo).where(TrackedRepo.repo == repo))
        s.commit()

def _link_repo(url: str) -> str:
    """owner/repo out of a github link, or "" — matched on the whole path pair so
    `owner/foo` never swallows `owner/foobar`."""
    u = (url or "").strip().rstrip("/").lower()
    for pre in ("https://github.com/", "http://github.com/", "github.com/"):
        if u.startswith(pre):
            parts = u[len(pre):].split("/")
            return f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else ""
    return ""

def ban_repo(repo: str):
    """Permanently ban a GitHub repo (owner/repo): it never reaches the feed again
    (dropped in prefilter) and is pulled out of the watchlist here. Its already-shown
    topics also lose `kept`, because the .md export reads that flag — a ban that only
    hid the card still wrote the repo into the file the user was about to save."""
    with _lock, _session() as s:
        if not s.get(BannedRepo, repo):
            s.add(BannedRepo(repo=repo, banned_at=_now()))
        s.execute(delete(StarHistory).where(StarHistory.repo == repo))
        s.execute(delete(TrackedRepo).where(TrackedRepo.repo == repo))
        target = repo.strip().lower()
        for t in s.execute(select(Topic).where(Topic.kept == 1)).scalars().all():
            try:
                links = json.loads(t.links)
            except Exception:
                continue
            if any(_link_repo(l) == target for l in links):
                t.kept = 0
        s.commit()

def unban_repo(repo: str):
    # Case-insensitive on the way OUT as well as in: the rows written before bans were
    # normalised carry GitHub's own capitals, and an exact match would leave them
    # unliftable — the screen would keep showing a ban the button could not remove.
    with _lock, _session() as s:
        s.execute(delete(BannedRepo)
                  .where(func.lower(BannedRepo.repo) == (repo or "").lower())); s.commit()

def get_banned_repos() -> set[str]:
    with _lock, _session() as s:
        return set(s.execute(select(BannedRepo.repo)).scalars().all())

def list_banned() -> list[dict]:
    with _lock, _session() as s:
        rows = s.execute(select(BannedRepo).order_by(desc(BannedRepo.banned_at))).scalars().all()
        return [{"repo": r.repo, "url": f"https://github.com/{r.repo}"} for r in rows]

def get_tracked_detail() -> list[dict]:
    with _lock, _session() as s:
        rows = []
        for tr in s.execute(select(TrackedRepo)).scalars().all():
            latest = s.execute(
                select(StarHistory.stars, StarHistory.timestamp).where(StarHistory.repo == tr.repo)
                .order_by(desc(StarHistory.timestamp)).limit(1)).first()
            stars, measured = (latest[0], latest[1]) if latest else (None, None)
            rows.append((tr.repo, tr.added, stars, measured, tr.description))
    # velocity() takes _lock itself — call outside the block to avoid re-entrant deadlock
    return [{"repo": r, "stars": stars, "velocity": velocity(r), "added": added,
             "last_measured": measured, "description": desc, "url": f"https://github.com/{r}"}
            for (r, added, stars, measured, desc) in rows]
