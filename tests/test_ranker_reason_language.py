"""The shown description must be Ukrainian, whatever language the signal was in.

`_base.txt` says so with RIGHT/WRONG examples and it holds most of the time — but on
2026-08-01 one scoring batch of 120 came back entirely in English (33 of 71 shown
descriptions). It is per-batch roulette, not a missing rule: three offline replays of
the same tweets produced 0 English reasons, so a prompt edit cannot be verified to
have fixed it. Hence a code check — see the omitted-signal gap-fill for the same
pattern of not trusting the weak model to obey on a long reply.

The target language here is the synthetic `cyrillic_lang` catalogue, not `uk`: the
Ukrainian catalogue ships only in the private repo, and nothing below is specific to
it — the rule is "the target script, whatever it is".
"""
from topicparser.ranker import fix_reason_language


def rows(*reasons):
    return [{"i": i, "score": 80, "reason": r, "title": f"T{i}"}
            for i, r in enumerate(reasons)]


class Client:
    def __init__(self, reply="{}"):
        self.reply, self.calls = reply, []

    def make(self, messages):
        self.calls.append(messages)
        return self.reply


def test_ukrainian_reasons_cost_no_call(cyrillic_lang):
    c = Client()
    out = fix_reason_language(rows("Голосовий ввід для Mac.", "Модель від OpenAI."), c, lang=cyrillic_lang)
    assert c.calls == []
    assert [r["reason"] for r in out] == ["Голосовий ввід для Mac.", "Модель від OpenAI."]


def test_an_english_reason_is_rewritten(cyrillic_lang):
    c = Client('{"fixed":{"1":"Модель, яка дивиться відео."}}')
    out = fix_reason_language(rows("Українською.", "A model that watches video."), c, lang=cyrillic_lang)
    assert len(c.calls) == 1
    assert out[1]["reason"] == "Модель, яка дивиться відео."
    assert out[0]["reason"] == "Українською."


def test_titles_are_never_touched(cyrillic_lang):
    """`title` must stay ENGLISH — the fix is for `reason` only."""
    c = Client('{"fixed":{"0":"Опис українською."}}')
    out = fix_reason_language(rows("An English description."), c, lang=cyrillic_lang)
    assert out[0]["title"] == "T0"


def test_a_broken_reply_leaves_everything_alone(cyrillic_lang):
    out = fix_reason_language(rows("An English description."), Client("not json at all"), lang=cyrillic_lang)
    assert out[0]["reason"] == "An English description."


def test_a_dead_api_leaves_everything_alone(cyrillic_lang):
    class Dead:
        def make(self, messages):
            raise RuntimeError("429 rate limit")

    out = fix_reason_language(rows("An English description."), Dead(), lang=cyrillic_lang)
    assert out[0]["reason"] == "An English description."


def test_a_replacement_that_is_still_english_is_refused(cyrillic_lang):
    c = Client('{"fixed":{"0":"Still english, just reworded."}}')
    out = fix_reason_language(rows("An English description."), c, lang=cyrillic_lang)
    assert out[0]["reason"] == "An English description."


def test_rows_without_a_reason_are_ignored(cyrillic_lang):
    c = Client()
    out = fix_reason_language([{"i": 0, "score": 40}], c, lang=cyrillic_lang)
    assert c.calls == []
    assert out == [{"i": 0, "score": 40}]


def test_an_out_of_range_index_in_the_reply_is_ignored(cyrillic_lang):
    c = Client('{"fixed":{"7":"Опис."}}')
    out = fix_reason_language(rows("An English description."), c, lang=cyrillic_lang)
    assert out[0]["reason"] == "An English description."


def test_rank_repairs_an_english_reason_end_to_end(cyrillic_lang):
    """The guarantee has to hold through rank(), not just in isolation."""
    from topicparser.models import Signal
    from topicparser.ranker import rank

    sig = Signal.make(source="x", title="@lab", description="A new model shipped.",
                      url="http://x/1", date="", profile="AI")

    class Client:
        def __init__(self):
            self.n = 0

        def make(self, messages):
            self.n += 1
            if self.n == 1:                      # the scoring pass, in English
                return ('{"scored":[{"i":0,"score":80,'
                        '"reason":"A new model shipped today.","title":"New model"}]}')
            if self.n == 2:                      # clustering
                return '{"groups":[],"stale":[]}'
            # dedup is skipped (nothing shown before), so this is the repair call
            return '{"fixed":{"0":"Лабораторія випустила нову модель."}}'

    out = rank([sig], [], Client(), system_prompt="p", keep=70, lang=cyrillic_lang)
    assert out["topics"][0]["why"] == "Лабораторія випустила нову модель."
