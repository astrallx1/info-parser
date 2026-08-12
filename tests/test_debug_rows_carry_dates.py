"""The debug log is what `replay.py` re-scores, and it dropped the date on the floor.

`_scored_rows` writes source/title/url/text/score/reason, while `replay.load_signals`
reads `r.get("date")` — a key that was never written, so every replayed signal carried
an empty date. It also wrote `kept: None` on every row, which nothing has ever read."""
import json
import topicparser.store as store
from topicparser import replay
from topicparser.models import Signal
from topicparser.pipeline import run


class Collector:
    source = "x"
    def collect(self, name, cfg):
        return [Signal.make(source="x", title="@a", description="d",
                            url="https://x.com/a/status/1",
                            date="2026-08-19T09:00:00+00:00", profile=name)]


class Client:
    def make(self, m):
        return '{"scored":[{"i":0,"score":90,"reason":"r","title":"T"}]}'


def _debug_run(tmp_path):
    store.DB_PATH = str(tmp_path / "t.db"); store.init_db()
    run(selected=["AI"], profiles={"AI": {"x": {"accounts": ["a"]}}},
        collectors=[Collector()], client=Client(), threshold=70,
        x_days=3000, gh_days=3000, prompt_loader=lambda n: "RULES",
        debug_dir=str(tmp_path / "debug"))
    f = sorted((tmp_path / "debug").glob("run-*.json"))[-1]
    return f, json.load(open(f, encoding="utf-8"))


def test_a_scored_row_keeps_the_signal_date(tmp_path):
    _, d = _debug_run(tmp_path)
    row = d["profiles"]["AI"]["scored"][0]
    assert row["date"] == "2026-08-19T09:00:00+00:00"
    assert "kept" not in row          # written on every row, read by nothing


def test_replay_rebuilds_the_signal_with_its_date(tmp_path):
    f, _ = _debug_run(tmp_path)
    signals, _before = replay.load_signals(str(f), "AI")
    assert signals[0].date == "2026-08-19T09:00:00+00:00"
