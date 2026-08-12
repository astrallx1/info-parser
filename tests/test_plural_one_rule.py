"""C2 — the plural rule lives twice, under a docstring promising it cannot.

`i18n._plural_form` and `pluralForm` in `index.html` implement the same one/few/many
choice, inside a design whose whole point is ONE catalogue serving both halves so they
cannot drift. Nothing bites today; it bites the day somebody edits one side, and the
symptom would be «2 тем готово» on one surface and the right form on the other.

The check runs the REAL JavaScript — extracted from the live `index.html`, not
transcribed here, because a transcription would be a third copy of the very thing this
test exists to stop. Node is used only as a calculator; the app still has no build step
and no JS dependency, and the test skips where node is absent rather than failing.
"""
import json
import re
import os
import shutil
import subprocess

import pytest

from topicparser import i18n

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "topicparser", "ui", "index.html")

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is not installed; the JS half cannot run")


def _js_plural_form() -> str:
    """The function as it actually stands in the UI."""
    src = open(UI, encoding="utf-8").read()
    m = re.search(r"function pluralForm\(n\)\{.*?\n\}", src, re.S)
    assert m, "pluralForm is gone from index.html, or it was renamed"
    return m.group(0)


def _run_js(lang: str, numbers: list[int]) -> list[str]:
    script = f"""
    const LANG = {json.dumps(lang)};
    {_js_plural_form()}
    console.log(JSON.stringify({json.dumps(numbers)}.map(pluralForm)));
    """
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                         check=True, timeout=30)
    return json.loads(out.stdout)


@pytest.mark.parametrize("lang", ["uk", "en"])
def test_both_halves_answer_the_same_form(lang):
    numbers = list(range(0, 121))
    assert _run_js(lang, numbers) == [i18n._plural_form(lang, n) for n in numbers]


def test_the_ukrainian_exceptions_are_the_ones_that_matter():
    """A guard on the guard: if both sides drifted to the SAME wrong rule the test
    above still passes, so pin the cases a single plural form gets wrong."""
    assert [i18n._plural_form("uk", n) for n in (1, 2, 5, 11, 12, 14, 21, 22, 25)] \
        == ["one", "few", "many", "many", "many", "many", "one", "few", "many"]
