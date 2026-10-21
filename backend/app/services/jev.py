"""依 TypeSafe 官方 v1 HTTP 契約呼叫，政策不放在模型裡。"""
import json
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.logging_config import log_failure
from app.services.redact import scrub


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Result:
    response: dict | None
    duration_ms: int
    error: str | None = None
    retry_seconds: int = 0
    http_status: int | None = None


def post_json(url, key, payload, timeout):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError("response_size")
            return response.status, json.loads(raw), 0
    except urllib.error.HTTPError as error:
        retry = error.headers.get("Retry-After", "60")
        return error.code, None, min(3600, max(60, int(retry))) if retry.isdigit() else 60


def probability(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1


def valid_response(data, questions):
    if not isinstance(data, dict) or not isinstance(data.get("model"), str):
        return False
    answers, usage = data.get("answers"), data.get("usage")
    if (
        not isinstance(answers, dict)
        or set(answers) != set(questions)
        or not isinstance(usage, dict)
    ):
        return False
    if any(
        type(usage.get(key)) is not int or usage[key] < 0
        for key in ("input_tokens", "output_tokens")
    ):
        return False
    for key, question in questions.items():
        answer = answers[key]
        if not isinstance(answer, dict) or answer.get("type") != question["type"]:
            return False
        if question["type"] == "noul":
            if not probability(answer.get("noul")):
                return False
            continue
        probabilities = answer.get("probabilities")
        criteria = question["criteria"]
        expected = (
            set(criteria)
            if question["type"] == "choice"
            else {str(i) for i in range(len(criteria))}
        )
        if (
            not probability(answer.get("confidence"))
            or not isinstance(probabilities, dict)
            or set(probabilities) != expected
            or not all(probability(v) for v in probabilities.values())
            or abs(sum(probabilities.values()) - 1) > 0.02
        ):
            return False
        if question["type"] == "choice":
            if answer.get("choice") not in expected:
                return False
        elif (
            type(answer.get("score")) not in (int, float)
            or not math.isfinite(answer["score"])
            or not 0 <= answer["score"] <= len(criteria) - 1
            or not isinstance(answer.get("legend"), dict)
            or set(answer["legend"]) != expected
        ):
            return False
    return True


def ask(state, questions, settings) -> Result:
    from app.services.credentials import resolve

    try:
        key = resolve("JEV_API_KEY", settings)
    except Exception as error:
        log_failure("mwb.jev", "jev_ask_failed", error)
        return Result(None, 0, "key_unavailable")
    if not key:
        return Result(None, 0, "missing_key")
    payload = scrub({"model": settings.jev_model, "state": state, "questions": questions})
    started = time.perf_counter()
    try:
        status, data, retry = post_json(
            resolve("JEV_API_BASE_URL", settings) + "/systemone",
            key.get_secret_value(),
            payload,
            settings.jev_timeout_seconds,
        )
        elapsed = round((time.perf_counter() - started) * 1000)
        if status != 200:
            return Result(None, elapsed, f"http_{status}", retry, status)
        if not valid_response(data, payload["questions"]):
            return Result(None, elapsed, "invalid_response", 60, status)
        return Result(data, elapsed, http_status=status)
    except Exception as error:
        log_failure("mwb.jev", "jev_ask_failed", error)
        # urllib 例外可能含請求或網址；不能記錄第三方原文。
        return Result(None, round((time.perf_counter() - started) * 1000), "connection_error", 60)
