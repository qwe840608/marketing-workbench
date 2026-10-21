"""Retry status regressions use isolated storage and never contact platforms."""

import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.logging_config import JsonFormatter
from app.models import Account, Brand, CommentBackfill, CommentPoll, DmBackfill, Setting, Staff
from app.schemas.meta import ApiCallFinish, ApiCallStart
from app.services import comment_backfill, meta_api
from app.services.access import BrandAccess

NOW = datetime(2026, 9, 30, 4, 0, tzinfo=UTC)


@pytest.fixture
def waiting_data(client, monkeypatch):
    for module in (meta_api, comment_backfill):
        monkeypatch.setattr(module, "utc_now", lambda: NOW)
    factory = client.app.state.session_factory
    with factory.begin() as session:
        brand = Brand(slug="waiting-test", name="[隔離驗收] 等待狀態")
        staff = Staff(
            username="waiting-test",
            display_name="[隔離驗收] 管理員",
            role="admin",
            password_hash="unused",
        )
        session.add_all([brand, staff])
        session.flush()
        account = Account(
            brand_id=brand.id, platform="facebook", external_id="waiting-test", name="[隔離驗收] FB"
        )
        session.add(account)
        session.flush()
        session.add(DmBackfill(account_id=account.id, window_end=NOW, next_poll_at=NOW))
        comments = CommentBackfill(account_id=account.id, window_start=NOW, window_end=NOW)
        session.add(comments)
        session.flush()
        session.add(
            CommentPoll(
                account_id=account.id,
                resource="backfill:90d",
                backfill_id=comments.id,
                next_poll_at=NOW,
            )
        )
        identities = account.id, staff.id
    return factory, identities


def read_status(data, module, settings):
    factory, (_, staff_id) = data
    with factory() as session:
        return module.status(BrandAccess(session, session.get(Staff, staff_id)), settings=settings)[
            "accounts"
        ][0]


@pytest.mark.parametrize("module", [comment_backfill])
@pytest.mark.parametrize(
    "reason,error",
    [
        ("system_budget", "meta_rate_limited"),
        ("meta_usage", "meta_rate_limited"),
        ("meta_unstable", "meta_timeout"),
        (None, "meta_rate_limited"),
    ],
)
@pytest.mark.parametrize("expired", [False, True])
def test_pause_reason_survives_cooldown(waiting_data, settings, module, reason, error, expired):
    factory, _ = waiting_data
    retry = NOW + timedelta(minutes=5)
    with factory.begin() as session:
        for model in (DmBackfill, CommentPoll):
            row = session.scalar(select(model))
            row.last_error, row.next_poll_at = error, retry
        state = {
            "blocked_until": (NOW + timedelta(seconds=-1 if expired else 60)).isoformat(),
            "usage_percent": 8,
        }
        if reason:
            state["reason"] = reason
        session.add(Setting(key=meta_api.BUDGET_KEY, value_json=state))
    status = read_status(waiting_data, module, settings)
    assert status["state"] == ("waiting" if expired else "throttled")
    assert status["wait_reason"] == (reason or "meta_usage")
    assert status["retry_at"] == retry
    assert status["usage_percent"] == 8
    assert status["calls_per_hour"] == settings.meta_api_calls_per_hour


@pytest.mark.parametrize("module", [comment_backfill])
@pytest.mark.parametrize(
    "error", ["work_budget", "meta_timeout", "meta_server_error", "network_error"]
)
def test_retryable_without_global_cooldown(waiting_data, settings, module, error):
    with waiting_data[0].begin() as session:
        for model in (DmBackfill, CommentPoll):
            session.scalar(select(model)).last_error = error
    status = read_status(waiting_data, module, settings)
    assert status["state"] == "waiting"
    assert status["wait_reason"] == ("work_budget" if error == "work_budget" else "meta_unstable")
    assert status["retry_at"] == NOW


@pytest.mark.parametrize(
    "error", ["permissions_required", "meta_auth_error", "invalid_response", "invalid_pagination"]
)
def test_actionable_error_not_hidden_by_cooldown(waiting_data, settings, error):
    with waiting_data[0].begin() as session:
        row = session.scalar(select(CommentPoll))
        row.last_error, row.paused = error, error in {"permissions_required", "meta_auth_error"}
        meta_api.block(session, NOW, 60, reason="meta_usage")
    status = read_status(waiting_data, comment_backfill, settings)
    assert status["state"] == "error"
    with waiting_data[0]() as session:
        assert session.scalar(select(CommentPoll)).last_error == error
    assert status["wait_reason"] is None and status["retry_at"] is None


@pytest.mark.parametrize(
    "extra,reason",
    [
        ({"app_usage": {"call_count": 80}}, "meta_usage"),
        ({"http_status": 429}, "meta_usage"),
        ({"error_code": 613}, "meta_usage"),
        ({"http_status": 599}, "meta_unstable"),
        ({"http_status": 0}, "meta_unstable"),
        ({"error_code": -2, "error_subcode": 2534084}, "meta_unstable"),
        ({"error_code": 190, "app_usage": {"call_count": 90}}, "meta_auth"),
    ],
)
def test_finish_records_reason(waiting_data, settings, extra, reason):
    factory, _ = waiting_data
    with factory() as session:
        permit = meta_api.start_call(
            session,
            ApiCallStart(
                platform="facebook",
                account_external_id="waiting-test",
                source="metrics",
                operation="post",
                resource_id="waiting-test",
            ),
            settings,
        )
    with factory() as session:
        meta_api.finish_call(
            session,
            ApiCallFinish(
                **{"call_id": permit["call_id"], "http_status": 200, "duration_ms": 1, **extra}
            ),
        )
    with factory() as session:
        assert meta_api.budget(session)["reason"] == reason
    record = logging.LogRecord("mwb.meta", logging.WARNING, "", 0, "meta_rate_backoff", (), None)
    record.reason = reason
    assert json.loads(JsonFormatter().format(record))["reason"] == reason


def test_system_limit_preserves_real_usage(waiting_data, settings):
    settings.meta_api_calls_per_hour = 10
    factory, _ = waiting_data
    body = ApiCallStart(
        platform="facebook",
        account_external_id="waiting-test",
        source="metrics",
        operation="post",
        resource_id="waiting-test",
    )
    for _ in range(10):
        with factory() as session:
            permit = meta_api.start_call(session, body, settings)
        with factory() as session:
            meta_api.finish_call(
                session,
                ApiCallFinish(
                    call_id=permit["call_id"],
                    http_status=200,
                    duration_ms=1,
                    app_usage={"call_count": 8},
                ),
            )
    with factory() as session:
        assert not meta_api.start_call(session, body, settings)["allowed"]
    with factory() as session:
        assert meta_api.budget(session)["reason"] == "system_budget"
        assert meta_api.budget(session)["usage_percent"] == 8
