from topicparser.export import to_markdown, write_markdown

ALERTS = [
    {"repo": "a/hot", "url": "https://github.com/a/hot", "stars": 2654,
     "velocity": 700.4, "description": "Опис першого репо."},
    {"repo": "b/warm", "url": "https://github.com/b/warm", "stars": 5148,
     "velocity": 256.0, "description": "Опис другого репо."},
]
TOPICS = [{"title": "T1", "why": "W1", "score": 80,
           "links": ["https://github.com/x/y"], "kept": 1}]


def test_trending_section_comes_first():
    md = to_markdown(TOPICS, date="2026-08-06", alerts=ALERTS)
    assert "TRENDING  (2)" in md
    # the trending block sits ABOVE every source section, like the feed
    assert md.index("TRENDING") < md.index("GITHUB")


def test_trending_rows_carry_repo_velocity_stars_and_full_description():
    md = to_markdown(TOPICS, date="2026-08-06", alerts=ALERTS)
    assert "[a/hot](https://github.com/a/hot)" in md
    assert "+700 ★/day" in md
    # grouped by the CATALOGUE separator, like the feed — comma here because this
    # suite runs the English build (uk uses a non-breaking space)
    assert "2,654 ★" in md
    assert "Опис першого репо." in md            # description in full, never cut


def test_trending_sorted_by_velocity_desc():
    md = to_markdown(TOPICS, date="2026-08-06", alerts=list(reversed(ALERTS)))
    assert md.index("a/hot") < md.index("b/warm")


def test_no_alerts_no_trending_section():
    md = to_markdown(TOPICS, date="2026-08-06", alerts=[])
    assert "TRENDING" not in md


def test_alerts_survive_an_empty_topic_list():
    # a run can alert on a breakout while every topic was unkept — the .md must
    # still carry the trending block instead of collapsing to "0 topic(s)"
    md = to_markdown([], date="2026-08-06", alerts=ALERTS)
    assert "TRENDING" in md and "a/hot" in md


def test_missing_velocity_or_stars_renders_without_them():
    md = to_markdown(TOPICS, date="2026-08-06",
                     alerts=[{"repo": "c/bare", "url": "https://github.com/c/bare"}])
    assert "c/bare" in md and "★" not in md


def test_write_markdown_passes_alerts_through(tmp_path):
    path = tmp_path / "topics.md"
    write_markdown(TOPICS, str(path), date="2026-08-06", alerts=ALERTS)
    text = path.read_text(encoding="utf-8")
    assert "TRENDING" in text and "Опис першого репо." in text
