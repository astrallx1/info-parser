from topicparser.llm import OpenAIClient

class _Msg:  # minimal shape of the SDK response
    def __init__(self, content): self.message = type("M", (), {"content": content})
class _Resp:
    def __init__(self, content): self.choices = [_Msg(content)]

def test_make_returns_content(monkeypatch):
    calls = {}
    class FakeCompletions:
        def create(self, **kw): calls.update(kw); return _Resp('{"topics":[]}')
    class FakeChat: completions = FakeCompletions()
    class FakeSDK: chat = FakeChat()
    client = OpenAIClient(sdk=FakeSDK(), model="gpt-4.1-mini")
    out = client.make([{"role": "user", "content": "hi"}])
    assert out == '{"topics":[]}'
    assert calls["model"] == "gpt-4.1-mini"
    assert calls["response_format"] == {"type": "json_object"}
