"""The fallbacks used to carry the author's own taste and his interface language into
a copy that ships English-only and sells itself as subject-agnostic: `models.NICHE`
named crypto/Web3 and "dev shitposts", and `ranker.DEFAULT_GROUP` demanded a Ukrainian
`why`. Both only fire when a prompt file is missing, which is exactly when nobody is
watching — a fallback is a fallback because it runs one day."""
import re

from topicparser import ranker
from topicparser.models import NICHE

CYRILLIC = re.compile(r"[Ѐ-ӿ]")

# a subject is somebody's choice; a default must not make it for them
SOMEBODY_ELSES_TASTE = ("crypto", "web3", "defi", "shitpost", "ai/ml")


def test_the_niche_default_names_no_subject():
    # whole words: "defined" contains "defi", and a substring check would fail on it
    words = set(re.findall(r"[a-z0-9/]+", NICHE.lower()))
    for word in SOMEBODY_ELSES_TASTE:
        assert word not in words, f"{word!r} is the author's taste, not a default"


def test_no_fallback_prompt_hardcodes_a_language():
    for name in ("DEFAULT_SYSTEM", "DEFAULT_GROUP", "DEFAULT_XGATE", "DEFAULT_FEEDGATE",
                 "DEFAULT_DEDUP"):
        text = getattr(ranker, name, "")
        assert "Ukrainian" not in text, f"{name} hardcodes one interface language"
        assert not CYRILLIC.search(text), f"{name} carries Cyrillic"


def test_the_fallbacks_still_ask_for_the_json_they_parse():
    # de-personalising must not quietly break the shape the parsers expect
    assert '"scored"' in ranker.DEFAULT_SYSTEM
    assert '"groups"' in ranker.DEFAULT_GROUP
