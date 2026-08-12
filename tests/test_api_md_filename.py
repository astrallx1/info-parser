"""The save dialog should propose today's date, not a name that repeats every run."""
from datetime import date

from topicparser.api import _md_filename


def test_the_suggested_name_carries_the_date():
    assert _md_filename(date(2026, 8, 1)) == "topics-2026-08-01.md"


def test_single_digit_parts_are_padded():
    """Zero-padding keeps the files sorting chronologically in a folder listing."""
    assert _md_filename(date(2026, 1, 9)) == "topics-2026-01-09.md"


def test_it_defaults_to_today():
    assert _md_filename() == f"topics-{date.today().isoformat()}.md"
