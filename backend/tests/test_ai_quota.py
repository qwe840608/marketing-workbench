import pytest
from message_fixtures import send_data as send_data
from test_ai_resilience import CALL_API, UpstreamError
from test_ai_resilience import clock as clock
from test_stage3 import queued
from test_stage3 import stage as stage

from app.services import ai
from app.services.ai import providers


@pytest.mark.parametrize("location", ["message", "details", "response_json", "body"])
def test_google_free_quota_stops_immediately(settings, monkeypatch, clock, location):
    from google.genai.errors import APIError

    payload = {"error": {"message": "Quota exceeded: generate_content_free_tier_requests"}}
    error = APIError(429, payload) if location == "message" else UpstreamError(429)
    if location != "message":
        setattr(error, location, payload)
    calls = []

    def call(*args):
        calls.append(args[1])
        raise error

    monkeypatch.setattr(providers, "_call_api_once", call)
    result = CALL_API("gemini_api", "primary", "redacted", settings, "backup")
    assert result.error == "provider_quota_free_tier"
    assert calls == ["primary"] and clock[1] == [] and not result.fallback_used
    assert "free_tier_requests" not in repr(result)


@pytest.mark.parametrize(
    "provider,kind,expected",
    [
        ("gemini_api", "RESOURCE_EXHAUSTED", "provider_rate_limited"),
        ("openai_api", "rate_limit_exceeded", "provider_rate_limited"),
        ("openai_api", "insufficient_quota", "provider_quota_exhausted"),
        ("openai_api", "billing_not_active", "provider_quota_exhausted"),
        ("openai_api", "project_spend_limit_exceeded", "provider_quota_exhausted"),
        ("anthropic_api", "rate_limit_error", "provider_rate_limited"),
    ],
)
def test_quota_classification(settings, monkeypatch, clock, provider, kind, expected):
    error = UpstreamError(429, details={"error": {"type": kind}})
    calls = []

    def call(*args):
        calls.append(args[1])
        raise error

    monkeypatch.setattr(providers, "_call_api_once", call)
    result = CALL_API(provider, "primary", "redacted", settings, "backup")
    assert result.error == expected
    assert len(calls) == (8 if expected == "provider_rate_limited" else 1)


def test_long_google_wait_returns_without_sleep(settings, monkeypatch, clock):
    calls = []

    def call(*args):
        calls.append(args[1])
        raise UpstreamError(429, {"Retry-After": "90"})

    monkeypatch.setattr(providers, "_call_api_once", call)
    result = CALL_API("gemini_api", "primary", "redacted", settings, "backup")
    assert result.error == "provider_rate_limited" and result.retry_after_seconds == 90
    assert calls == ["primary"] and not clock[1]


@pytest.mark.parametrize("budget", [30, 60, 90])
def test_slow_primary_503_preserves_backup(settings, monkeypatch, clock, budget):
    settings = settings.model_copy(update={"ai_api_timeout_seconds": budget})
    calls = []

    def call(provider, model, prompt, bounded):
        calls.append((model, bounded.ai_api_timeout_seconds))
        if model == "primary":
            clock[0][0] += min(8, bounded.ai_api_timeout_seconds)
            raise UpstreamError(503)
        return providers.Result("done", model)

    monkeypatch.setattr(providers, "_call_api_once", call)
    result = CALL_API("gemini_api", "primary", "redacted", settings, "backup")
    assert result.error is None and result.fallback_used
    assert calls[-1][0] == "backup" and calls[-1][1] >= 20
    assert clock[0][0] <= budget - 20


@pytest.mark.parametrize("fallback", ["", "backup"])
def test_insufficient_initial_time_never_calls(settings, monkeypatch, clock, fallback):
    settings = settings.model_copy(update={"ai_api_timeout_seconds": 9})
    monkeypatch.setattr(providers, "_call_api_once", lambda *a: pytest.fail("時間不足不可請求"))
    result = CALL_API("gemini_api", "primary", "redacted", settings, fallback)
    assert result.error == "provider_time_exhausted" and not clock[1]


def test_fallback_wait_cannot_consume_reserved_time(settings, monkeypatch, clock):
    calls = []

    def call(*args):
        calls.append(args[1])
        clock[0][0] += 30
        raise UpstreamError(429, {"Retry-After": "15"})

    monkeypatch.setattr(providers, "_call_api_once", call)
    result = CALL_API("gemini_api", "primary", "redacted", settings, "backup")
    assert result.error == "provider_rate_limited"
    assert calls == ["primary"] and not clock[1]


@pytest.mark.parametrize("free_tier", [True, False])
def test_replayed_429_503_429_never_becomes_400(settings, monkeypatch, clock, free_tier):
    calls = []
    errors = [
        UpstreamError(
            429,
            details={
                "message": "Quota exceeded: free_tier" if free_tier else "Rate exceeded",
                "details": [{"@type": "google.rpc.RetryInfo", "retryDelay": "12.08s"}],
            },
        ),
        UpstreamError(503),
        UpstreamError(
            429, details={"details": [{"@type": "google.rpc.RetryInfo", "retryDelay": "50.5s"}]}
        ),
    ]

    def call(provider, model, prompt, bounded):
        calls.append((model, bounded.ai_api_timeout_seconds))
        if bounded.ai_api_timeout_seconds < 10:
            raise UpstreamError(400)
        raise errors[len(calls) - 1]

    monkeypatch.setattr(providers, "_call_api_once", call)
    result = CALL_API("gemini_api", "primary", "redacted", settings, "backup")
    assert result.error == ("provider_quota_free_tier" if free_tier else "provider_rate_limited")
    assert len(calls) == (1 if free_tier else 3)
    assert all(timeout >= 10 for _, timeout in calls)
    assert not result.fallback_used


def test_slow_failure_cannot_issue_tiny_fallback(settings, monkeypatch, clock):
    calls = []

    def call(*args):
        calls.append(args[1])
        clock[0][0] = 55
        raise UpstreamError(503)

    monkeypatch.setattr(providers, "_call_api_once", call)
    result = CALL_API("gemini_api", "primary", "redacted", settings, "backup")
    assert calls == ["primary"] and result.error == "provider_time_exhausted"
    assert not clock[1] and not result.fallback_used


def test_fallback_sleep_overshoot_never_calls(settings, monkeypatch, clock):
    calls = []

    def call(*args):
        calls.append(args[1])
        raise UpstreamError(503, {"Retry-After": "5"})

    monkeypatch.setattr(providers, "_call_api_once", call)
    monkeypatch.setattr(providers, "sleep", lambda _: clock[0].__setitem__(0, 100))
    result = CALL_API("gemini_api", "primary", "redacted", settings, "backup")
    assert calls == ["primary"] and result.error == "provider_time_exhausted"
    assert not result.fallback_used


def test_ideation_error_keeps_safe_quota_and_wait(stage, monkeypatch):
    from app.models.ideation import IdeationReport
    from app.services import ideation

    result = providers.Result(
        error="provider_rate_limited", retry_after_seconds=50.5, model="primary"
    )
    monkeypatch.setattr(ai, "run", lambda *args, **kwargs: result)
    report_id = queued(stage)
    ideation.process(stage.factory, stage.settings, report_id)
    with stage.factory() as session:
        row = session.get(IdeationReport, report_id)
        assert row.status == "failed"
        assert row.error == "文字模型未完成（provider_rate_limited;retry_after_seconds=50.5）"
