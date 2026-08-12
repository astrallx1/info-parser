from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

# A fallback only: it is used by `ranker.DEFAULT_SYSTEM`, which runs when a profile
# has no prompt file. Naming actual subjects here would hand every reader somebody
# else's taste, so it names none — WHAT is on-niche is the profile's own rules, and a
# fresh install seeds `_starter.txt` for exactly that.
NICHE = (
    "The niche is defined by the profile's own scoring rules, not here. Judge each "
    "signal against those rules; if none were supplied, judge whether it is news "
    "somebody following this profile's sources would want to write about. "
    "OUT of niche in every profile: personal life, and anything the sources "
    "clearly did not set out to cover."
)

@dataclass
class Signal:
    source: str
    title: str
    description: str
    url: str
    date: str
    profile: str
    stars: Optional[int] = None
    velocity: Optional[float] = None
    created: Optional[str] = None       # repo creation date (GitHub created_at); date == pushed_at (last modified)
    topics: list[str] = field(default_factory=list)   # the repo's own GitHub tags; always empty for a tweet

    # A hostile or broken feed has produced a 100 000-character title, which rides
    # into the scoring payload (paid for by the token) and into the DB. The second,
    # independent ceiling on the same path as the entity guard — deliberately so.
    TITLE_CAP = 200

    @classmethod
    def make(cls, *, source, title, description, url, date, profile,
             stars=None, velocity=None, created=None, topics=None) -> "Signal":
        return cls(source=source, title=(title or "")[:cls.TITLE_CAP],
                   description=(description or "")[:500],
                   url=url, date=date, profile=profile, stars=stars,
                   velocity=velocity, created=created, topics=list(topics or []))
