import time

# Errors worth trying again: rate limits, gateway hiccups, a server that fell over.
# Anything else (a bad key, a malformed request) will answer identically next time,
# and retrying it only makes a run take three times as long to fail.
RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}
DEFAULT_TIMEOUT = 120.0


def _worth_retrying(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status is None:
        # a timeout or a dropped connection carries no HTTP status at all
        return True
    try:
        return int(status) in RETRY_STATUS
    except (TypeError, ValueError):
        return True


class OpenAIClient:
    """Thin wrapper so ranker depends on .make(messages) -> str, not the SDK.

    It retries because of where it sits: the scoring pass is the most expensive
    thing a run does, it happens AFTER up to fifteen minutes of scraping, and
    nothing is persisted until the whole ranking returns. The gates, the
    clustering and the cross-run dedup are all crash-proof by design; this call
    was the one that could still throw a run away over a single 429."""

    def __init__(self, sdk, model: str, retries: int = 3, backoff: float = 2.0,
                 timeout: float = DEFAULT_TIMEOUT, sleep=time.sleep):
        self._sdk = sdk
        self._model = model
        self._retries = max(1, retries)
        self._backoff = backoff
        self._timeout = timeout
        self._sleep = sleep
        self._temperature_ok = True

    @classmethod
    def from_env(cls, api_key: str, model: str):
        from openai import OpenAI
        return cls(sdk=OpenAI(api_key=api_key), model=model)

    # Some models accept ONLY their default temperature. Measured live: gpt-5 and
    # gpt-5-mini answer `400 Unsupported value: 'temperature' does not support 0.2`,
    # 400 is deliberately not retried, so every batch failed and the run scored
    # nothing — from two models the Settings screen offers by name.
    #
    # Learned, not listed. A hardcoded list of model prefixes rots the moment OpenAI
    # ships the next one, and it rots SILENTLY in the direction that breaks a paid run.
    # This costs one wasted request per client, once, for any model that refuses.
    _TEMP_REFUSED = "does not support"

    def make(self, messages: list[dict]) -> str:
        delay = self._backoff
        attempt = 0
        # a `for` over the retries meant learning the temperature SPENT one of them —
        # and with retries=1 the loop then ended and `make` returned None
        while attempt < self._retries:
            try:
                extra = {"temperature": 0.2} if self._temperature_ok else {}
                resp = self._sdk.chat.completions.create(
                    model=self._model, messages=messages,
                    timeout=self._timeout,
                    response_format={"type": "json_object"}, **extra)
                return resp.choices[0].message.content
            except Exception as exc:
                if self._temperature_ok and "temperature" in str(exc) \
                        and self._TEMP_REFUSED in str(exc):
                    # this model takes its default only — remember and go again now,
                    # so the model the selector gained yesterday costs one request
                    # rather than every batch of the run
                    self._temperature_ok = False
                    continue          # same attempt, one parameter lighter
                attempt += 1
                if attempt >= self._retries or not _worth_retrying(exc):
                    raise
                self._sleep(delay)
                delay *= 2
