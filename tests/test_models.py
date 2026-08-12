from topicparser.models import Signal, NICHE

def test_signal_truncates_description():
    s = Signal.make(source="github", title="t", description="x" * 900,
                    url="https://a/b", date="2026-07-07T00:00:00Z", profile="AI")
    assert len(s.description) == 500
    assert s.stars is None

def test_signal_carries_created_date():
    # feed cards show a repo's creation date; the signal must carry it
    s = Signal.make(source="github", title="t", description="d", url="u",
                    date="2026-07-18T00:00:00Z", profile="AI",
                    created="2026-05-01T00:00:00Z")
    assert s.created == "2026-05-01T00:00:00Z"


def test_niche_defers_to_the_profile_rules():
    # it used to name the author's own subjects, which a shared default must not do
    low = NICHE.lower()
    assert "profile" in low and "rules" in low
