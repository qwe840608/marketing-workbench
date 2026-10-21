"""官方 API SDK。第三方例外不向外輸出原文。"""
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import isfinite
from random import uniform
from time import monotonic, sleep

import httpx

from app.logging_config import log_failure

try:
    import httpx2
except ImportError:
    httpx2 = httpx

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
MIN_REQUEST_SECONDS = 10
MIN_FALLBACK_SECONDS = 20


def temporary_error(code):
    code = code.split(";", 1)[0] if isinstance(code, str) else code
    if code in {
        "provider_timeout", "provider_connection_error", "provider_rate_limited",
        "provider_time_exhausted",
    }:
        return True
    if isinstance(code, str) and code.startswith("provider_http_"):
        status = code.removeprefix("provider_http_")
        return status.isdigit() and (int(status) in {408, 429} or 500 <= int(status) <= 599)
    return False


@dataclass
class Result:
    text: str = ""
    model: str = ""
    tokens_in: int | None = None
    tokens_out: int | None = None
    error: str | None = None
    duration_ms: int = 0
    fallback_used: bool = False
    retry_not_before: float | None = field(default=None, repr=False)
    retry_after_seconds: float | None = None

    @property
    def error_detail(self):
        # 沿用既有錯誤欄位，只附有限數值，不保存供應商錯誤文字或絕對時鐘。
        delay = self.retry_after_seconds
        if self.error in {"provider_rate_limited", "provider_quota_free_tier"} and (
            delay is not None and isfinite(delay) and delay >= 0
        ):
            return f"{self.error};retry_after_seconds={delay:g}"
        return self.error


def _payload(error):
    payload = (
        getattr(error, "response_json", None)
        or getattr(error, "body", None)
        or getattr(error, "details", None)
    )
    return payload.get("error", payload) if isinstance(payload, dict) else {}


def _contains_free_tier(value):
    if isinstance(value, str):
        return "free_tier" in value.lower()
    if isinstance(value, dict):
        return any(_contains_free_tier(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_free_tier(item) for item in value)
    return False


def error_code(error, provider=""):
    payload = _payload(error)
    if isinstance(payload, dict):
        details = payload.get("details") if isinstance(payload, dict) else None
        if isinstance(details, list) and any(
            isinstance(item, dict) and item.get("reason") == "API_KEY_INVALID" for item in details
        ):
            return "provider_invalid_key"
    code = getattr(error, "status_code", None) or getattr(error, "code", None)
    if type(code) is int and 400 <= code <= 599:
        if code == 429:
            if provider == "gemini_api" and (
                _contains_free_tier(payload)
                or _contains_free_tier(getattr(error, "message", None))
            ):
                return "provider_quota_free_tier"
            if provider == "openai_api" and isinstance(payload, dict) and any(
                isinstance(payload.get(key), str) and payload[key] in {
                    "insufficient_quota", "billing_not_active", "billing_hard_limit_reached",
                    "project_spend_limit_exceeded", "organization_usage_limit_exceeded",
                } for key in ("code", "type")
            ):
                return "provider_quota_exhausted"
            return "provider_rate_limited"
        return f"provider_http_{code}"
    chain, seen = error, set()
    while chain is not None and id(chain) not in seen:
        seen.add(id(chain))
        if (
            isinstance(chain, (TimeoutError, httpx.TimeoutException, httpx2.TimeoutException))
            or type(chain).__name__ == "APITimeoutError"
        ):
            return "provider_timeout"
        if (
            isinstance(chain, (httpx.NetworkError, httpx2.NetworkError))
            or type(chain).__name__ == "APIConnectionError"
        ):
            return "provider_connection_error"
        chain = chain.__cause__ or chain.__context__
    return "provider_failed"


def suggested_delay(error):
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None) or getattr(error, "headers", {}) or {}
    value = headers.get("retry-after") or headers.get("Retry-After")
    if value is not None:
        try:
            seconds = float(value)
        except (ValueError, TypeError):
            try:
                seconds = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                seconds = None
        if seconds is not None and isfinite(seconds):
            return max(0, seconds)
    payload = (
        getattr(error, "response_json", None)
        or getattr(error, "body", None)
        or getattr(error, "details", None)
    )
    if isinstance(payload, dict):
        payload = payload.get("error", payload)
        details = payload.get("details") if isinstance(payload, dict) else None
        for detail in details if isinstance(details, list) else []:
            if not isinstance(detail, dict) or not str(detail.get("@type", "")).endswith(
                "RetryInfo"
            ):
                continue
            value = detail.get("retryDelay")
            try:
                seconds = (
                    float(value.rstrip("s"))
                    if isinstance(value, str)
                    else float(value.get("seconds", 0)) + float(value.get("nanos", 0)) / 1e9
                )
                if isfinite(seconds):
                    return max(0, seconds)
            except (ValueError, TypeError, AttributeError):
                pass
    return None


def _attempts(provider, model, prompt, settings, deadline):
    result = Result(model=model, error="provider_time_exhausted")
    for attempt in range(4):
        remaining = deadline - monotonic()
        if remaining < MIN_REQUEST_SECONDS:
            return Result(model=model, error="provider_time_exhausted")
        bounded = settings.model_copy(update={"ai_api_timeout_seconds": remaining})
        try:
            result = _call_api_once(provider, model, prompt, bounded)
            if monotonic() >= deadline:
                return Result(model=model, error="provider_timeout")
            return result
        except Exception as error:
            log_failure("mwb.providers", "providers__attempts_failed", error)
            code = error_code(error, provider)
            result = Result(model=model, error=code)
            recommended = suggested_delay(error)
            if recommended is not None:
                result.retry_not_before = monotonic() + recommended
                result.retry_after_seconds = recommended
            status = (
                int(code.removeprefix("provider_http_"))
                if code.startswith("provider_http_")
                else None
            )
            if attempt == 3 or not (
                status in RETRYABLE_STATUS
                or code in {
                    "provider_timeout", "provider_connection_error", "provider_rate_limited"
                }
            ):
                break
            delay = recommended
            delay = delay if delay is not None else (2, 5, 10)[attempt] + uniform(0, 0.25)
            remaining = deadline - monotonic()
            if remaining < MIN_REQUEST_SECONDS and recommended is None:
                return Result(model=model, error="provider_time_exhausted")
            # 不截短供應商要求的等待後提早重送，也不建立超過上限的請求。
            if delay + MIN_REQUEST_SECONDS > remaining:
                break
            sleep(delay)
    return result


def call_api(provider, model, prompt, settings, fallback_model=""):
    deadline = monotonic() + settings.ai_api_timeout_seconds
    fallback_model = fallback_model if fallback_model != model else ""
    # 預留至少 20 秒或三分之一；短預算時先讓備援取得有意義的請求時間。
    reserved = max(MIN_FALLBACK_SECONDS, settings.ai_api_timeout_seconds / 3)
    primary_deadline = (
        deadline - reserved if fallback_model else deadline
    )
    result = _attempts(provider, model, prompt, settings, primary_deadline)
    if fallback_model and temporary_error(result.error):
        if deadline - monotonic() < MIN_REQUEST_SECONDS:
            return Result(model=fallback_model, error="provider_time_exhausted")
        if result.retry_not_before is not None:
            delay = max(0, result.retry_not_before - monotonic())
            # 不為遵守供應商等待而吃掉備援保留時間；也不能提早重送。
            if delay and delay + reserved > deadline - monotonic():
                return result
            if delay:
                sleep(delay)
        if deadline - monotonic() < MIN_REQUEST_SECONDS:
            return Result(model=fallback_model, error="provider_time_exhausted")
        result = _attempts(provider, fallback_model, prompt, settings, deadline)
        result.fallback_used = True
    return result


def _call_api_once(provider, model, prompt, settings):
    from app.services.ai_keys import resolve

    key = resolve(provider, settings).get_secret_value()
    timeout = settings.ai_api_timeout_seconds
    if provider == "gemini_api":
        from google import genai
        from google.genai import types

        with genai.Client(
            api_key=key,
            vertexai=False,
            http_options=types.HttpOptions(
                base_url="https://generativelanguage.googleapis.com",
                timeout=max(1, int(timeout * 1000)),
                retry_options=types.HttpRetryOptions(attempts=1),
                client_args={"trust_env": False, "follow_redirects": False},
            ),
        ) as client:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    max_output_tokens=settings.ai_max_output_tokens,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
        usage = response.usage_metadata
        tin = usage.prompt_token_count if usage else None
        tout = (
            (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
            if usage and usage.candidates_token_count is not None
            else None
        )
        complete = bool(response.candidates and response.candidates[0].finish_reason == "STOP")
        return Result(
            response.text or "",
            response.model_version or model,
            tin,
            tout,
            None if complete else "incomplete_output",
        )
    if provider == "openai_api":
        from openai import DefaultHttpxClient, OpenAI

        with OpenAI(
            api_key=key,
            base_url="https://api.openai.com/v1",
            max_retries=0,
            timeout=timeout,
            http_client=DefaultHttpxClient(trust_env=False, follow_redirects=False),
        ) as client:
            response = client.responses.create(
                model=model,
                input=prompt,
                store=False,
                max_output_tokens=settings.ai_max_output_tokens,
            )
        usage = response.usage
        return Result(
            response.output_text,
            response.model,
            usage.input_tokens if usage else None,
            usage.output_tokens if usage else None,
            None if response.status == "completed" else "incomplete_output",
        )
    if provider == "anthropic_api":
        from anthropic import Anthropic, DefaultHttpxClient

        with Anthropic(
            api_key=key,
            base_url="https://api.anthropic.com",
            max_retries=0,
            timeout=timeout,
            http_client=DefaultHttpxClient(trust_env=False, follow_redirects=False),
        ) as client:
            response = client.messages.create(
                model=model,
                max_tokens=settings.ai_max_output_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
        return Result(
            "".join(block.text for block in response.content if block.type == "text"),
            response.model,
            response.usage.input_tokens,
            response.usage.output_tokens,
            None if response.stop_reason == "end_turn" else "incomplete_output",
        )
    return Result(error="provider_unavailable")
