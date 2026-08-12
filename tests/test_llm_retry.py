"""The scoring call is the most expensive thing the app does and used to be the only
unguarded one: no timeout, no retry, no backoff, while the gates, the clustering and
the dedup are all crash-proof by design. One 429 fifteen minutes into a run destroyed
it along with every scoring call already paid for."""
import pytest

from topicparser.llm import OpenAIClient


class _Msg:
    def __init__(self, content): self.message = type("M", (), {"content": content})


class _Resp:
    def __init__(self, content): self.choices = [_Msg(content)]


class _Boom(Exception):
    """Stands in for an SDK error carrying an HTTP status."""
    def __init__(self, status=None):
        super().__init__(f"boom {status}")
        self.status_code = status


def _sdk(answers):
    """`answers` is a list of either exceptions to raise or strings to return."""
    calls = []

    class FakeCompletions:
        def create(self, **kw):
            calls.append(kw)
            a = answers[len(calls) - 1]
            if isinstance(a, Exception):
                raise a
            return _Resp(a)

    class FakeChat:
        completions = FakeCompletions()

    class FakeSDK:
        chat = FakeChat()

    return FakeSDK(), calls


def test_a_rate_limit_is_retried_and_the_run_survives():
    sdk, calls = _sdk([_Boom(429), '{"ok":1}'])
    slept = []
    c = OpenAIClient(sdk=sdk, model="m", sleep=slept.append)
    assert c.make([{"role": "user", "content": "x"}]) == '{"ok":1}'
    assert len(calls) == 2
    assert slept, "a retry must wait before trying again"


def test_a_network_error_with_no_status_is_retried():
    sdk, calls = _sdk([ConnectionError("dropped"), '{"ok":1}'])
    c = OpenAIClient(sdk=sdk, model="m", sleep=lambda s: None)
    assert c.make([{"role": "user", "content": "x"}]) == '{"ok":1}'
    assert len(calls) == 2


def test_backoff_grows_and_the_last_error_is_raised():
    sdk, calls = _sdk([_Boom(503), _Boom(503), _Boom(503)])
    slept = []
    c = OpenAIClient(sdk=sdk, model="m", retries=3, backoff=2.0, sleep=slept.append)
    with pytest.raises(_Boom):
        c.make([{"role": "user", "content": "x"}])
    assert len(calls) == 3                  # tried, then gave the error back
    assert slept == [2.0, 4.0]              # waits between attempts, growing


def test_a_bad_key_is_not_retried():
    # 401 will never succeed on the next attempt; retrying it only makes a run
    # take three times as long to fail.
    sdk, calls = _sdk([_Boom(401), '{"ok":1}'])
    slept = []
    c = OpenAIClient(sdk=sdk, model="m", sleep=slept.append)
    with pytest.raises(_Boom):
        c.make([{"role": "user", "content": "x"}])
    assert len(calls) == 1
    assert slept == []


def test_every_call_carries_a_timeout():
    # without one a hung connection stalls the run forever with no way out
    sdk, calls = _sdk(['{"ok":1}'])
    OpenAIClient(sdk=sdk, model="m").make([{"role": "user", "content": "x"}])
    assert calls[0]["timeout"] > 0
