"""Batch 5 uses isolated databases and mock platform transports only."""

import json
from datetime import timedelta

import pytest
from message_fixtures import send_data as send_data
from test_notify import DAY, incoming, notices
from test_notify import setup as setup

from app.models import (
    Account,
    Message,
)
from app.models.base import utc_now
from app.services import ingest, notify


@pytest.mark.parametrize(
    "text,blocked",
    [
        ("服務後不一定會提升成效", False),
        ("未必能改善困擾", False),
        ("不能保證100%達成效果", False),
        ("無法保證達成目標", False),
        ("不會解決問題", False),
        ("我們不保證提升成效", False),
        ("百分之百達成效果", True),
        ("完全達成效果", True),
        ("保證達成目標", True),
        ("保證１００％達成效果", True),
        ("服務後一定提升成效", True),
        ("可以解決問題", True),
        ("不會解決問題但保證達成目標", True),
        ("不會解決問題而且完全達成效果", True),
        ("不會解決問題提升成效有保證", True),
    ],
)
def test_promise_examples(text, blocked):
    from brand_fixtures import FORBIDDEN

    from app.services.content_safety import forbidden_promise

    assert forbidden_promise(text, FORBIDDEN) is blocked


def source(mid, at, direction="in", peer="20001"):
    return dict(
        external_id=mid,
        thread_external_id=peer,
        kind="dm",
        contact={"external_id": peer},
        direction=direction,
        author_type="fan" if direction == "in" else "brand",
        text="隔離驗收訊息",
        sent_at=at.isoformat(),
    )


def save_event(d, event, origin="history", settings=None):
    with d["factory"]() as s:
        return ingest.events(s, json.dumps(event).encode(), origin, settings)


def test_history_dedup_echo_and_no_side_effects(client):
    """Retired DM workflow: its API is absent, with no side effects."""
    from test_dm_backfill_history import assert_retired

    assert_retired(client)


def test_history_permissions_pause_and_resume(client):
    """Retired DM workflow: its API is absent, with no side effects."""
    from test_dm_backfill_history import assert_retired

    assert_retired(client)


def test_history_rejects_unrecorded_calls_and_outside_window(client):
    """Retired DM workflow: its API is absent, with no side effects."""
    from test_dm_backfill_history import assert_retired

    assert_retired(client)


def test_history_shares_call_budget_and_retains_checkpoint(client):
    """Retired DM workflow: its API is absent, with no side effects."""
    from test_dm_backfill_history import assert_retired

    assert_retired(client)


def line_event(d, at, mid="line-redelivery", redelivery=True, event_id="evt-redelivery"):
    return dict(
        platform="line",
        account_external_id="10001",
        external_id=event_id,
        signature_ok=True,
        payload={
            "events": [
                {
                    "webhookEventId": event_id,
                    "timestamp": int(at.timestamp() * 1000),
                    "deliveryContext": {"isRedelivery": redelivery},
                    "replyToken": "isolated-token",
                    "message": {"id": mid},
                }
            ]
        },
        messages=[source(mid, utc_now())],
    )


def line_account(d):
    with d["factory"].begin() as s:
        account = s.get(Account, d["account"])
        account.platform = "line"
        account.token_ref = "LINE_CHANNEL_ACCESS_TOKEN"
        from app.models import Contact

        s.get(Contact, d["contact"]).platform = "line"


def test_line_redelivery_timestamp_dedup_without_reply_tokens(client):
    """Retired DM workflow: its API is absent, with no side effects."""
    from test_dm_backfill_history import assert_retired

    assert_retired(client)


def test_line_old_redelivery_keeps_original_order_no_jobs(client):
    """Retired DM workflow: its API is absent, with no side effects."""
    from test_dm_backfill_history import assert_retired

    assert_retired(client)


@pytest.mark.parametrize(
    "historical,old", [(True, False), (True, True), (False, True), (False, False)]
)
def test_notification_history_and_redelivery_policy(setup, settings, historical, old):
    factory, brand_id, clock = setup
    thread, mid = incoming(
        setup, at=DAY - timedelta(hours=25 if old else 1), urgency=1, reputation=1
    )
    with factory.begin() as s:
        m = s.get(Message, mid)
        m.created_at = DAY
        m.is_historical = historical
        m.is_redelivery = not historical
    notify.plan(factory, DAY)
    rows = notices(setup)
    if historical or old:
        assert rows == []
        assert notify.claim_deliveries(factory, settings, DAY) == []
    else:
        assert any(r.kind == "urgent" for r in rows)
        messages = notify.claim_deliveries(factory, settings, DAY)[0]["messages"]
        text = str(messages)
        assert "原生 App" in text and "?view=" not in text


def test_history_only_thread_no_overdue_but_response_time_counts(client):
    """Retired DM workflow: its API is absent, with no side effects."""
    from test_dm_backfill_history import assert_retired

    assert_retired(client)


def test_old_history_manual_reclassify_never_calls_cloud(client):
    """Retired DM workflow: its API is absent, with no side effects."""
    from test_dm_backfill_history import assert_retired

    assert_retired(client)
