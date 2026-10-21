import pytest

from app.services.ai import providers


class UpstreamError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__("credential-and-response-must-never-be-persisted")


@pytest.mark.parametrize("code", [429, 503])
def test_transient_api_error_retries_with_shared_deadline(settings, monkeypatch, code):
    clock, calls = [0.0], []
    monkeypatch.setattr(providers, "monotonic", lambda: clock[0])
    monkeypatch.setattr(providers, "uniform", lambda *a: 0)
    monkeypatch.setattr(
        providers, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )

    def call(provider, model, prompt, bounded):
        calls.append((provider, model, prompt, bounded.ai_api_timeout_seconds))
        if len(calls) == 1:
            clock[0] += 3
            raise UpstreamError(code)
        return providers.Result(text="請由專人確認可預約日期。", model=model)

    monkeypatch.setattr(providers, "_call_api_once", call)
    result = providers.call_api("gemini_api", "test-model", "已遮蔽文字", settings)
    assert result.error is None
    assert calls == [
        ("gemini_api", "test-model", "已遮蔽文字", 60),
        ("gemini_api", "test-model", "已遮蔽文字", 55),
    ]


@pytest.mark.parametrize("code", [401, 402, 403, 503])
def test_persistent_error_is_bounded_and_hides_provider_text(settings, monkeypatch, code):
    calls = []
    monkeypatch.setattr(providers, "sleep", lambda _: None)

    def call(*args):
        calls.append(args)
        raise UpstreamError(code)

    monkeypatch.setattr(providers, "_call_api_once", call)
    result = providers.call_api("gemini_api", "test-model", "已遮蔽文字", settings)
    assert len(calls) == (4 if code == 503 else 1)
    assert result.error == f"provider_http_{code}"
    assert "credential" not in repr(result)


def test_no_retry_when_first_attempt_uses_time_budget(settings, monkeypatch):
    clock, calls = [0.0], []
    monkeypatch.setattr(providers, "monotonic", lambda: clock[0])
    monkeypatch.setattr(providers, "sleep", lambda _: pytest.fail("不可延長逾時上限"))

    def call(*args):
        calls.append(args)
        clock[0] = 58
        raise UpstreamError(503)

    monkeypatch.setattr(providers, "_call_api_once", call)
    result = providers.call_api("gemini_api", "test-model", "已遮蔽文字", settings)
    assert len(calls) == 1 and result.error == "provider_time_exhausted"
