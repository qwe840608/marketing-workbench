from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from types import SimpleNamespace

import httpx
import httpx2
import pytest
from message_fixtures import send_data as send_data

from app.services.ai import providers

CALL_API = providers.call_api


class UpstreamError(Exception):
    def __init__(self, code, headers=None, details=None):
        self.code = code
        self.response = SimpleNamespace(headers=headers or {})
        self.details = details
        super().__init__("secret-response-must-not-escape")


@pytest.fixture
def clock(monkeypatch):
    time, sleeps = [0.0], []
    monkeypatch.setattr(providers, "monotonic", lambda: time[0])
    monkeypatch.setattr(providers, "uniform", lambda *a: 0.125)

    def sleep(seconds):
        sleeps.append(seconds)
        time[0] += seconds

    monkeypatch.setattr(providers, "sleep", sleep)
    return time, sleeps


@pytest.mark.parametrize("provider", ["gemini_api", "openai_api", "anthropic_api"])
@pytest.mark.parametrize("code", [408, 429, 500, 502, 503, 504])
def test_four_attempts_with_jitter(settings, monkeypatch, clock, provider, code):
    calls = []

    def call(p, model, prompt, bounded):
        calls.append(bounded.ai_api_timeout_seconds)
        raise UpstreamError(code)

    monkeypatch.setattr(providers, "_call_api_once", call)
    result = CALL_API(provider, "primary", "redacted", settings)
    assert calls == [60, 57.875, 52.75, 42.625]
    assert clock[1] == [2.125, 5.125, 10.125]
    expected = "provider_rate_limited" if code == 429 else f"provider_http_{code}"
    assert result.error == expected and "secret" not in repr(result)


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectTimeout("secret"),
        httpx.ReadTimeout("secret"),
        httpx2.ReadTimeout("secret"),
        TimeoutError("secret"),
        httpx.ConnectError("secret"),
    ],
)
def test_transport_retry(settings, monkeypatch, clock, error):
    calls = []

    def call(*a):
        calls.append(True)
        raise error

    monkeypatch.setattr(providers, "_call_api_once", call)
    result = CALL_API("gemini_api", "primary", "redacted", settings)
    assert len(calls) == 4
    assert result.error in {"provider_timeout", "provider_connection_error"}


@pytest.mark.parametrize("code", [400, 401, 402, 403, 404, 422])
def test_permanent_failure_no_retry_or_fallback(settings, monkeypatch, clock, code):
    calls = []

    def call(*a):
        calls.append(a[1])
        raise UpstreamError(code)

    monkeypatch.setattr(providers, "_call_api_once", call)
    result = CALL_API("gemini_api", "primary", "redacted", settings, "backup")
    assert calls == ["primary"] and clock[1] == []
    assert result.error == f"provider_http_{code}"


@pytest.mark.parametrize("delay", ["7", "7.5", "0"])
def test_retry_after(settings, monkeypatch, clock, delay):
    calls = []

    def call(*a):
        calls.append(True)
        if len(calls) == 1:
            raise UpstreamError(503, {"Retry-After": delay})
        return providers.Result("done", a[1])

    monkeypatch.setattr(providers, "_call_api_once", call)
    assert CALL_API("gemini_api", "primary", "redacted", settings).error is None
    assert clock[1] == [float(delay)]


@pytest.mark.parametrize("delay", ["4.5s", {"seconds": "4", "nanos": 500000000}])
def test_google_retry_info(settings, monkeypatch, clock, delay):
    from google.genai.errors import APIError

    calls = []

    def call(*a):
        calls.append(True)
        if len(calls) == 1:
            raise APIError(
                503,
                {
                    "error": {
                        "details": [
                            {
                                "@type": "type.googleapis.com/google.rpc.RetryInfo",
                                "retryDelay": delay,
                            }
                        ]
                    }
                },
            )
        return providers.Result("done", a[1])

    monkeypatch.setattr(providers, "_call_api_once", call)
    assert CALL_API("gemini_api", "primary", "redacted", settings).error is None
    assert clock[1] == [4.5]


def test_http_date_and_invalid_delay():
    delay = format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
    assert 28 < providers.suggested_delay(UpstreamError(503, {"retry-after": delay})) <= 30
    for value in ("bad", "NaN", "Infinity"):
        assert providers.suggested_delay(UpstreamError(503, {"retry-after": value})) is None


def test_retry_after_beyond_total_budget_no_early_fallback(settings, monkeypatch, clock):
    calls = []

    def call(*a):
        calls.append(a[1])
        raise UpstreamError(429, {"Retry-After": "90"})

    monkeypatch.setattr(providers, "_call_api_once", call)
    result = CALL_API("gemini_api", "primary", "redacted", settings, "backup")
    assert calls == ["primary"] and clock[1] == [] and result.error == "provider_rate_limited"


def test_no_call_after_deadline_or_sleep_overshoot(settings, monkeypatch, clock):
    calls = []

    def call(*a):
        calls.append(a[1])
        clock[0][0] = 58
        raise UpstreamError(503)

    monkeypatch.setattr(providers, "_call_api_once", call)
    assert (
        CALL_API("gemini_api", "primary", "redacted", settings).error == "provider_time_exhausted"
    )
    assert calls == ["primary"] and not clock[1]
    clock[0][0] = 0
    monkeypatch.setattr(providers, "sleep", lambda _: clock[0].__setitem__(0, 100))
    monkeypatch.setattr(
        providers, "_call_api_once", lambda *a: (_ for _ in ()).throw(UpstreamError(503))
    )
    assert (
        CALL_API("gemini_api", "primary", "redacted", settings).error == "provider_time_exhausted"
    )


def test_primary_timeout_reserves_backup_budget(settings, monkeypatch, clock):
    calls = []

    def call(p, model, prompt, bounded):
        calls.append((model, bounded.ai_api_timeout_seconds))
        if model == "primary":
            clock[0][0] += bounded.ai_api_timeout_seconds
            raise httpx.ReadTimeout("secret")
        return providers.Result("done", model)

    monkeypatch.setattr(providers, "_call_api_once", call)
    result = CALL_API("gemini_api", "primary", "redacted", settings, "backup")
    assert calls == [("primary", 40), ("backup", 20)]
    assert result.model == "backup" and result.fallback_used


def test_fallback_identifier_validation(client, send_data):
    url = f"/api/ai/settings?brand_id={send_data['brand']}"
    config = client.get(url).json()["config"]
    config["gemini_fallback_model"] = "https://untrusted.invalid/model"
    assert client.put(url, json=config).status_code == 422


def test_google_invalid_key_no_retry(settings, monkeypatch, clock):
    from google.genai.errors import APIError

    calls = []

    def call(*a):
        calls.append(True)
        raise APIError(400, {"error": {"details": [{"reason": "API_KEY_INVALID"}]}})

    monkeypatch.setattr(providers, "_call_api_once", call)
    assert (
        CALL_API("gemini_api", "primary", "redacted", settings, "backup").error
        == "provider_invalid_key"
    )
    assert len(calls) == 1 and not clock[1]
