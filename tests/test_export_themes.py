"""A long source section is split into THEMES inside the .md.

The owner reads the file top to bottom; seventy GitHub topics in one score-ordered
wall is what he asked to break up (agents in one pile, skills in another). The split
is a sub-layer INSIDE the source section, not a replacement for it: the sections and
their order still mirror the feed.
"""
from topicparser.export import to_markdown, _theme, THEME_MIN


def _gh(title, score, topics=None):
    return {"title": title, "why": "w", "kept": 1, "score": score, "source": "gh",
            "links": ["https://github.com/a/" + title], "topics": topics or []}


def test_long_section_gets_theme_subheadings():
    rows = ([_gh(f"claude-code-skill-{i}", 90 - i) for i in range(5)]
            + [_gh(f"agent-harness-{i}", 80 - i) for i in range(5)])
    md = to_markdown(rows, date="2026-09-06")
    assert "Skills and plugins" in md
    assert "Agents and harnesses" in md
    # every topic still present, none lost to the regrouping
    for t in rows:
        assert t["title"] in md


def test_theme_reads_repo_tags_not_only_the_title():
    t = _gh("ponytail", 90, topics=["claude-code", "skill"])
    assert _theme(t) == "skills"


def test_short_section_stays_flat():
    rows = [_gh(f"claude-code-skill-{i}", 90 - i) for i in range(THEME_MIN - 1)]
    md = to_markdown(rows, date="2026-09-06")
    assert "Skills and plugins" not in md


def test_news_sections_stay_flat():
    """A headline is not a repo name: the same keywords misfile it, so only GitHub
    is themed. Tweets keep reading as one score-ordered list."""
    rows = [dict(_gh(f"agent skill story {i}", 90 - i), source="tw",
                 links=["https://x.com/a/status/1"]) for i in range(12)]
    md = to_markdown(rows, date="2026-09-06")
    assert "Skills and plugins" not in md
    assert "Agents and harnesses" not in md
