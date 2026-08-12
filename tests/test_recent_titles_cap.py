"""`recent_titles` is resent inside EVERY scoring batch, plus the group and dedup calls.

It was read as "every topic in the freshness window", so its size grows with the age of
the database: 83 titles after two runs, and a year of runs would put hundreds of them in
front of every batch on a model billed by the token. The window still decides what is
recent; this only bounds how many of the newest are carried."""
import topicparser.store as store
from topicparser import pipeline
from topicparser.models import Signal


class Collector:
    source = "x"
    def collect(self, name, cfg):
        from datetime import datetime, timezone
        return [Signal.make(source="x", title="@a", description="d",
                            url="https://x.com/a/status/1",
                            date=datetime.now(timezone.utc).isoformat(), profile=name)]


class Client:
    def make(self, m):
        return '{"scored":[{"i":0,"score":90,"reason":"r","title":"T"}]}'


def test_only_the_newest_titles_reach_the_scorer(tmp_path, monkeypatch):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    for i in range(pipeline.RECENT_TITLES_CAP + 40):
        store.insert_topic(title=f"topic {i}", why="w", links=[f"https://e.com/{i}"],
                           signature=f"topic {i}", score=90, profile="AI")

    seen = {}
    real = pipeline.ranker.rank
    def spy(signals, recent_titles, *a, **kw):
        seen["titles"] = list(recent_titles)
        return real(signals, recent_titles, *a, **kw)
    monkeypatch.setattr(pipeline.ranker, "rank", spy)

    pipeline.run(selected=["AI"], profiles={"AI": {"x": {"accounts": ["a"]}}},
                 collectors=[Collector()], client=Client(),
                 threshold=70, x_days=3, gh_days=60,
                 prompt_loader=lambda name: "RULES")

    assert len(seen["titles"]) == pipeline.RECENT_TITLES_CAP
    # newest kept, oldest dropped: the cap must not cost the most recent run its dedup
    assert f"topic {pipeline.RECENT_TITLES_CAP + 39}" in seen["titles"]
    assert "topic 0" not in seen["titles"]


# --- and the cap must survive the profile loop -------------------------------------
#
# `recent_titles` is capped once, before the loop, and every topic a profile produces
# is appended to it so the NEXT profile dedups against this run's own output. Nothing
# re-applied the cap, so the list a second profile carries is `cap + everything the
# first profile produced` — and it rides inside every scoring batch plus the group and
# dedup calls, which is what the cap exists to stop.
#
# Re-slicing `[:CAP]` after the loop is the wrong fix and does the opposite: the list
# is NEWEST-FIRST while `append` puts new titles at the END, so the slice keeps the
# oldest and throws away exactly the fresh titles it was told to carry forward.


def test_the_titles_a_run_produces_go_to_the_FRONT(tmp_path):
    """Newest-first is the order the list is in, so this run's own topics belong at
    the head — that is also the half a re-slice would silently discard."""
    from topicparser import pipeline

    titles = ["old-1", "old-2"]
    pipeline._carry_title(titles, "brand new", cap=3)

    assert titles[0] == "brand new"


def test_the_carried_list_never_grows_past_the_cap(tmp_path):
    from topicparser import pipeline

    titles = ["a", "b", "c"]
    for t in ["d", "e", "f"]:
        pipeline._carry_title(titles, t, cap=3)

    assert len(titles) == 3
    assert titles == ["f", "e", "d"], "the newest three, newest first"
