"""The run-finished banner's count.

The declension rules themselves live in `i18n.plural` and are tested there for both
languages; this only pins that the banner still goes through them.
"""
import pytest

from topicparser.api import _topics_ready


@pytest.mark.parametrize("n,expected", [
    (0, "0 topics ready"), (1, "1 topic ready"), (2, "2 topics ready"),
    (11, "11 topics ready"),
])
def test_the_banner_uses_the_catalogue(n, expected):
    assert _topics_ready(n) == expected
