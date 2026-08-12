"""The traction numbers reached the card and never reached the file.

`ranker._repo_meta` stamps stars, velocity, the two dates and the repo's own GitHub
tags onto every topic, and `export._traction_lines` was written to print the first two.
But the `.md` is ALWAYS assembled from the database (`Api.save_md` -> `_md_topics` ->
`store.get_last_run_topics`), and `shown_topics` had nowhere to put any of it — so the
export read those keys off a row that never carried them and printed nothing, on every
run since the feature was added. Measured on a real export: 70 GitHub topics, zero star
lines. The screen showed them only because the FIRST render draws `run_parser`'s own
return value; a restart collapsed the cards to a title and a score too.

The tests that covered the export handed `_topic_block` a dict with `stars` in it, so
they passed against data the app could not produce — which is why this is pinned at the
round trip, not at the renderer."""
import topicparser.store as store
from topicparser import i18n
from topicparser.api import Api

META = {"stars": 12400, "velocity": 85.4, "created": "2026-07-01T00:00:00Z",
        "updated": "2026-08-30T00:00:00Z", "topics": ["llm", "rust"]}


def _insert(**kw):
    kw.setdefault("run_id", "r1")
    return store.insert_topic(title="a/b", why="w", links=["https://github.com/a/b"],
                              signature="a/b", score=90, profile="AI", source="gh", **kw)


def test_repo_meta_survives_the_database(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    _insert(meta=META)

    got = store.get_last_run_topics()[0]
    for key, value in META.items():
        assert got[key] == value, key


def test_a_topic_with_no_repo_meta_reads_as_none(tmp_path):
    """A tweet has no stars, and the export omits the line rather than printing 0."""
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    _insert()

    got = store.get_last_run_topics()[0]
    assert got["stars"] is None and got["velocity"] is None
    assert got["topics"] == []


def test_rows_written_before_the_column_existed_still_read(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    _insert()
    with store._engine.begin() as conn:          # the pre-column shape: no meta at all
        conn.exec_driver_sql("UPDATE shown_topics SET meta = NULL")

    got = store.get_last_run_topics()[0]
    assert got["stars"] is None and got["topics"] == []


def test_the_md_export_carries_the_star_count(tmp_path):
    """The end of the chain, and the only place the owner actually reads."""
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    _insert(meta=META)
    api = Api(profiles={}, build_collectors=lambda: [], build_client=lambda: None,
              threshold=70, x_days=3, gh_days=60)
    # what `run_parser` does at the end of a run; there is no restore path any more
    api._last_topic_ids = {t["id"] for t in store.get_last_run_topics()}

    out = tmp_path / "topics.md"
    assert api.save_md(str(out))["ok"]
    text = out.read_text(encoding="utf-8")
    assert f"{i18n.t('md.stars_label')}: 12{i18n.t('locale.thousands')}400" in text
    assert f"{i18n.t('md.growth_label')}: +85" in text


def test_a_run_writes_the_repo_band_it_produced(tmp_path, monkeypatch):
    """The other half: the pipeline has to HAND the meta over, or the column stays
    empty and nothing above changes anything."""
    from topicparser import pipeline
    from topicparser.models import Signal
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()

    sig = Signal.make(source="github", title="a/b", description="a thing",
                      url="https://github.com/a/b", date="2026-08-30T00:00:00Z",
                      profile="AI", stars=12400, created="2026-07-01T00:00:00Z",
                      topics=["llm"])

    class Col:
        source = "github"
        def collect(self, name, cfg): return [sig]

    monkeypatch.setattr(pipeline.ranker, "rank", lambda *a, **kw: {
        "topics": [{"title": "a/b", "why": "w", "score": 90, "links": [sig.url],
                    "source": "gh", "stars": sig.stars, "velocity": None,
                    "created": sig.created, "updated": None, "topics": sig.topics}],
        "scored": [{"i": 0, "score": 90}], "raw": "", "dropped": {}})

    pipeline.run(selected=["AI"], profiles={"AI": {"github": {"topics": ["llm"]}}},
                 collectors=[Col()], client=None, threshold=70, x_days=3, gh_days=60,
                 debug_dir=str(tmp_path))

    got = store.get_last_run_topics()[0]
    assert got["stars"] == 12400 and got["topics"] == ["llm"]
