"""The description-language repair used to be hardcoded to Ukrainian.

Left that way, an English build would flag EVERY description as drifted (no Cyrillic,
plenty of Latin words) and pay for a call that rewrites the whole feed into Ukrainian.
The target language is now read from the catalogue, and the repair is deliberately
asymmetric: a Latin-script target only fires when the text is MOSTLY non-Latin, since
a wrong repair costs more than a missed one.

The Cyrillic side uses the synthetic `cyrillic_lang` catalogue rather than `uk`: the
Ukrainian catalogue ships only in the private repo, and this behaviour is not specific
to it.
"""
import json

from topicparser import ranker


class FakeClient:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def make(self, messages):
        self.calls.append(messages)
        return self.reply


def _rows(*texts):
    return [{"reason": t} for t in texts]


def test_english_target_leaves_english_alone():
    client = FakeClient("{}")
    rows = _rows("A voice input tool for Mac and Windows that works offline.")
    assert ranker.fix_reason_language(rows, client, lang="en") == rows
    assert client.calls == []          # no call at all, so no cost


def test_english_target_repairs_a_description_that_drifted():
    client = FakeClient(json.dumps({"fixed": {"0": "A voice input tool that works offline."}}))
    rows = _rows("Голосовий ввід для Mac та Windows, працює офлайн.")
    out = ranker.fix_reason_language(rows, client, lang="en")
    assert out[0]["reason"] == "A voice input tool that works offline."
    assert "ENGLISH" in client.calls[0][0]["content"].upper()


def test_english_target_keeps_a_latin_name_inside_english():
    # a product name in another script must not drag a whole English sentence in
    client = FakeClient("{}")
    rows = _rows("Zhipu's new model runs locally on a laptop and needs 2 GB of RAM.")
    assert ranker.fix_reason_language(rows, client, lang="en") == rows
    assert client.calls == []


def test_a_cyrillic_target_still_repairs_english(cyrillic_lang):
    client = FakeClient(json.dumps({"fixed": {"0": "Голосовий ввід, працює офлайн."}}))
    rows = _rows("Hold a key and speak — AI polishes your text into any app.")
    out = ranker.fix_reason_language(rows, client, lang=cyrillic_lang)
    assert out[0]["reason"] == "Голосовий ввід, працює офлайн."
    assert "UKRAINIAN" in client.calls[0][0]["content"].upper()


def test_a_replacement_in_the_wrong_language_is_refused(cyrillic_lang):
    original = "Hold a key and speak — AI polishes your text into any app."
    client = FakeClient(json.dumps({"fixed": {"0": "Still English, sorry about that."}}))
    out = ranker.fix_reason_language(_rows(original), client, lang=cyrillic_lang)
    assert out[0]["reason"] == original


def test_short_stubs_are_never_repaired(cyrillic_lang):
    client = FakeClient("{}")
    rows = _rows("Ponytail")
    assert ranker.fix_reason_language(rows, client, lang=cyrillic_lang) == rows
    assert client.calls == []
