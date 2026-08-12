from topicparser import i18n
from topicparser.export import to_markdown, write_markdown

def test_markdown_lists_kept_only():
    topics = [{"title": "T1", "why": "W1", "links": ["u1"], "kept": 1},
              {"title": "T2", "why": "W2", "links": ["u2"], "kept": 0}]
    md = to_markdown(topics, date="2026-07-07")
    assert "T1" in md and "T2" not in md and "u1" in md

def test_write_markdown_writes_utf8_file(tmp_path):
    path = tmp_path / "topics.md"
    topics = [{"title": "GPT — launch", "why": "W", "links": ["u1"], "kept": 1}]
    write_markdown(topics, str(path), date="2026-07-11")
    raw = path.read_bytes()
    assert b"\xe2\x80\x94" in raw                  # em-dash as UTF-8, not â€" mojibake
    text = raw.decode("utf-8")                     # decodes cleanly as UTF-8
    assert "# " + i18n.t("md.title", date="2026-07-11") in text
    assert "GPT — launch" in text


def test_markdown_grouped_by_source_mirrors_feed():
    # the .md must be IDENTICAL to the tool feed: sections by SOURCE with
    # `## Twitter` / `## GitHub` headers (feed labels), Twitter first, then GitHub,
    # each sorted by score desc. NO profile grouping — the feed mixes profiles too.
    topics = [
        {"title": "GH-high", "why": "W", "score": 95, "profile": "AI",
         "links": ["https://github.com/a/b"], "kept": 1},
        {"title": "X-low", "why": "W", "score": 71, "profile": "AI",
         "links": ["https://x.com/u/status/1"], "kept": 1},
        {"title": "X-high", "why": "W", "score": 90, "profile": "Crypto",
         "links": ["https://x.com/u/status/2"], "kept": 1},
        {"title": "GH-low", "why": "W", "score": 72, "profile": "AI",
         "links": ["https://github.com/c/d"], "kept": 1},
    ]
    md = to_markdown(topics, date="2026-07-15")
    # source section headers present (upper-cased labels, feed's sources)
    assert "TWITTER" in md and "GITHUB" in md
    # Twitter section fully precedes GitHub section
    assert md.index("TWITTER") < md.index("GITHUB")
    # profiles are NOT used to group (mixed under one source header, like the feed)
    assert "## AI" not in md and "## Crypto" not in md
    # within each source: score desc
    assert md.index("X-high") < md.index("X-low")
    assert md.index("GH-high") < md.index("GH-low")
    # every X topic precedes every GitHub topic
    assert md.index("X-low") < md.index("GH-high")


def test_markdown_readability_counts_and_separators():
    topics = [
        {"title": "X-a", "why": "W", "score": 90, "links": ["https://x.com/u/status/1"], "kept": 1},
        {"title": "X-b", "why": "W", "score": 80, "links": ["https://x.com/u/status/2"], "kept": 1},
        {"title": "GH-a", "why": "W", "score": 75, "links": ["https://github.com/a/b"], "kept": 1},
    ]
    md = to_markdown(topics, date="2026-07-17")
    # a summary line names the per-source counts
    assert "2 from Twitter" in md and "1 from GitHub" in md
    # section header carries its own count
    assert "TWITTER  (2)" in md and "GITHUB  (1)" in md
    # posts within a section are separated by the soft divider (2 X posts -> 1 divider)
    assert md.count("· · ·") >= 1


def test_markdown_other_source_section_last():
    topics = [
        {"title": "GH", "why": "W", "score": 80, "links": ["https://github.com/a/b"], "kept": 1},
        {"title": "OtherSig", "why": "W", "score": 90, "links": ["https://example.com/x"], "kept": 1},
    ]
    md = to_markdown(topics, date="2026-07-17")
    # Інше section comes after GitHub even though its score is higher (source order wins)
    assert md.index("GITHUB") < md.index("OTHER")
