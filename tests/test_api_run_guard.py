"""Two clicks must not start two runs.

`run_parser` read `_running`, then set it, with nothing between the two — so two
threads of the pywebview bridge (a double click, or the UI plus a keyboard shortcut)
could both pass the check and both start scraping: twice the cost of the most
expensive thing this app does, with two sets of writes interleaved."""
import threading
import time
from topicparser.api import Api


def test_clicks_arriving_while_a_run_is_open_are_all_refused():
    started, release = [], threading.Event()

    def build_collectors():
        started.append(1)
        release.wait(5)          # hold the run open while the other clicks arrive
        raise RuntimeError("far enough — the guard is what is under test")

    api = Api(profiles={"AI": {"github": {"topics": ["mcp"]}}},
              build_collectors=build_collectors, build_client=lambda: object(),
              threshold=70, x_days=3, gh_days=60)
    sel = {"AI": {"github": {"topics": ["mcp"]}}}
    refused = []

    def click():
        out = api.run_parser(sel)
        if isinstance(out, dict) and out.get("error"):
            refused.append(out["error"])

    threads = [threading.Thread(target=click) for _ in range(8)]
    for t in threads:
        t.start()
    time.sleep(0.3)              # every click has now been made
    assert len(started) == 1, f"{len(started)} runs started, expected 1"
    assert len(refused) == 7, f"{len(refused)} refused, expected 7"
    release.set()
    for t in threads:
        t.join(5)


def test_a_new_run_is_allowed_once_the_previous_one_ends():
    # the guard must not latch: it releases in `finally`, failure or not.
    started = []

    def build_collectors():
        started.append(1)
        raise RuntimeError("done")

    api = Api(profiles={"AI": {"github": {"topics": ["mcp"]}}},
              build_collectors=build_collectors, build_client=lambda: object(),
              threshold=70, x_days=3, gh_days=60)
    sel = {"AI": {"github": {"topics": ["mcp"]}}}
    api.run_parser(sel)
    api.run_parser(sel)
    assert len(started) == 2
