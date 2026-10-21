import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from conftest import login as shared_login
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import func, select
from test_classify import answer

from app.models import (
    Account,
    Brand,
    Classification,
    InboundJob,
    Message,
    Notification,
    NotificationDelivery,
    Setting,
    Staff,
    Thread,
)
from app.schemas.notify import DeliveryResult, NotificationPolicy
from app.services import classify, jev, notify
from app.services.passwords import hash_password

DAY = datetime(2026, 9, 26, 2, tzinfo=UTC)  # 台北 10:00
NIGHT = DAY.replace(hour=13)  # 台北 21:00


@pytest.fixture
def setup(client, settings, monkeypatch):
    factory = client.app.state.session_factory
    settings.notify_line_channel_access_token = SecretStr(secrets.token_urlsafe(32))
    settings.notify_line_group_id = "C" + secrets.token_hex(16)
    settings.ingest_api_key = SecretStr(secrets.token_urlsafe(32))
    clock = [DAY]
    monkeypatch.setattr(notify, "utc_now", lambda: clock[0])
    with factory.begin() as session:
        brand = Brand(slug="notify-test", name="隔離通知測試品牌")
        session.add(brand)
        session.flush()
        brand_id = brand.id
        session.add(
            Setting(
                key=notify.policy_key(brand.id),
                value_json={
                    **NotificationPolicy(enabled=True).model_dump(),
                    "group_id": settings.notify_line_group_id,
                    "enabled_at": (DAY - timedelta(days=1)).isoformat(),
                },
            )
        )
    return factory, brand_id, clock


def incoming(
    setup,
    *,
    at=DAY,
    kind="comment_thread",
    platform="facebook",
    intent="booking",
    urgency=1,
    reputation=0,
    text="想預約服務",
    classified=True,
    thread_id=None,
):
    factory, brand_id, _ = setup
    with factory.begin() as session:
        if thread_id:
            thread = session.get(Thread, thread_id)
            thread.status = "pending"
        else:
            account = Account(
                brand_id=brand_id,
                platform=platform,
                external_id=str(uuid4()),
                name="隔離測試帳號",
                status="connected",
            )
            session.add(account)
            session.flush()
            thread = Thread(
                brand_id=brand_id,
                account_id=account.id,
                external_id=str(uuid4()),
                kind=kind,
            )
            session.add(thread)
            session.flush()
        thread.last_inbound_at = at
        message = Message(
            thread_id=thread.id,
            external_id=str(uuid4()),
            direction="in",
            author_type="fan",
            text=text,
            sent_at=at,
            created_at=at,
        )
        session.add(message)
        session.flush()
        session.add(InboundJob(message_id=message.id, task="notify"))
        if classified:
            context, _ = classify.context_for(session, message)
            values = {"intent": intent, "urgency": urgency, "public_reputation_risk": reputation}
            session.add(
                Classification(
                    message_id=message.id,
                    engine="jev",
                    intent=intent,
                    sentiment="neutral",
                    sensitive=False,
                    action="skip" if intent == "spam" else "auto",
                    confidence=0.99,
                    raw_json={"signals": values},
                    input_hash=classify.fingerprint(message.text, context),
                )
            )
        return thread.id, message.id


def notices(setup, status="pending"):
    with setup[0]() as session:
        return list(
            session.scalars(
                select(Notification).where(Notification.status == status).order_by(Notification.id)
            )
        )


def sent(factory, delivery, code=200, already=False):
    return notify.finish(
        factory,
        delivery["id"],
        DeliveryResult(lease_id=delivery["lease_id"], status_code=code, already_accepted=already),
    )


@pytest.mark.parametrize(
    "attempted,reason", [(False, "new"), (True, "urgency"), (False, "urgency")]
)
def test_legacy_delivery_cannot_send_reply_links(setup, settings, attempted, reason):
    factory, _, _ = setup
    incoming(setup)
    notify.plan(factory, DAY)
    work = notify.claim_deliveries(factory, settings, DAY)[0]
    with factory.begin() as session:
        delivery = session.get(NotificationDelivery, work["id"])
        delivery.status = "pending"
        delivery.first_attempt_at = DAY if attempted else None
        delivery.lease_until = None
        delivery.next_attempt_at = DAY
        delivery.messages_json = [{"type": "text", "text": "legacy reply link /?thread_id=1"}]
        notice = session.scalar(select(Notification).where(Notification.delivery_id == work["id"]))
        notice.reason = reason
    result = notify.claim_deliveries(factory, settings, DAY)
    if not attempted and reason == "urgency":
        assert len(result) == 1
        assert "原生 App" in result[0]["messages"][0]["text"]
        assert "thread_id" not in str(result)
    else:
        assert result == []
        with factory() as session:
            assert session.get(NotificationDelivery, work["id"]).error == "notification_retired"


def test_long_emergency_retry_preserves_all_chunks(setup, settings):
    factory, _, _ = setup
    for _ in range(20):
        incoming(setup, text="😀" * 400)
    notify.plan(factory, DAY)
    first = notify.claim_deliveries(factory, settings, DAY)[0]
    assert len(first["messages"]) > 1
    sent(factory, first, code=503)
    second = notify.claim_deliveries(factory, settings, DAY + timedelta(minutes=1))[0]
    assert second["messages"] == first["messages"]
    assert second["retry_key"] == first["retry_key"]


def test_normal_messages_never_create_deadline_reminders(setup, settings):
    factory, _, _ = setup
    incoming(setup, urgency=0, intent="price")
    for now in (DAY, DAY + timedelta(hours=3), DAY + timedelta(hours=21)):
        notify.plan(factory, now)
        assert notices(setup) == []
        assert notify.claim_deliveries(factory, settings, now) == []


def test_dm_never_notifies_even_when_urgent_or_previously_queued(setup, settings):
    factory, brand_id, _ = setup
    thread, message = incoming(setup, kind="dm", urgency=1, reputation=1, intent="complaint")
    notify.plan(factory, DAY)
    assert notices(setup) == []
    with factory.begin() as session:
        delivery = NotificationDelivery(
            brand_id=brand_id,
            recipient=settings.notify_line_group_id,
            retry_key=str(uuid4()),
            next_attempt_at=DAY,
            messages_json=[{"type": "text", "text": "緊急留言通知｜legacy"}],
        )
        session.add(delivery)
        session.flush()
        session.add(
            Notification(
                brand_id=brand_id,
                thread_id=thread,
                message_id=message,
                kind="urgent",
                reason="complaint",
                due_at=DAY,
                delivery_id=delivery.id,
            )
        )
    assert notify.claim_deliveries(factory, settings, DAY) == []


def test_new_within_five_minutes_and_idempotence(setup, settings):
    factory, _, clock = setup
    incoming(setup)
    notify.plan(factory, clock[0])
    due = [r for r in notices(setup) if r.kind == "urgent"]
    assert len(due) == 1 and due[0].due_at <= DAY + timedelta(minutes=5)
    work = notify.claim_deliveries(factory, settings, DAY)
    assert len(work) == 1 and len(work[0]["messages"]) <= 5
    assert "原生 App" in work[0]["messages"][0]["text"]
    assert notify.claim_deliveries(factory, settings, DAY) == []
    assert sent(factory, work[0]) == {"status": "sent"}
    assert sent(factory, work[0]) == {"status": "sent"}
    notify.plan(factory, DAY)
    assert notify.claim_deliveries(factory, settings, DAY) == []


@pytest.mark.parametrize(
    "kind,intent,urgency,risk,expected",
    [
        ("comment_thread", "complaint", 0.45, 0.96, "public_reputation_risk"),
        ("comment_thread", "complaint", 0.45, 0.5, "complaint"),
        ("comment_thread", "booking", 0.75, 0, "urgency"),
        ("dm", "complaint", 0.45, 0.96, None),
        ("dm", "booking", 0.75, 0, None),
        ("dm", "booking", 0.74, 0, None),
        ("dm", "spam", 1, 1, None),
        ("comment_thread", "spam", 1, 1, None),
    ],
)
def test_emergency_conditions(kind, intent, urgency, risk, expected):
    assert (
        notify.emergency(
            kind,
            {"intent": intent, "urgency": urgency, "public_reputation_risk": risk},
            NotificationPolicy(),
        )
        == expected
    )


def test_h13_now_h26_never_and_reputation_threshold_reuses_answers(setup, settings):
    factory, brand_id, clock = setup
    clock[0] = NIGHT
    h13, _ = incoming(
        setup,
        at=NIGHT,
        kind="comment_thread",
        platform="facebook",
        text="騙子公司，大家不要被騙",
        intent="other",
        urgency=0.45,
        reputation=0.96,
    )
    incoming(
        setup,
        at=NIGHT,
        platform="facebook",
        text="點擊驗證，否則停權",
        intent="spam",
        urgency=1,
        reputation=1,
    )
    notify.plan(factory, NIGHT)
    assert all(r.thread_id == h13 for r in notices(setup))
    assert [r for r in notices(setup) if r.reason == "public_reputation_risk"][0].due_at == NIGHT
    with factory.begin() as session:
        row = session.scalar(select(Setting).where(Setting.key == notify.policy_key(brand_id)))
        row.value_json = {**row.value_json, "public_reputation_risk_threshold": 0.99}
    notify.plan(factory, NIGHT)
    assert not notices(setup)
    with factory.begin() as session:
        row = session.scalar(select(Setting).where(Setting.key == notify.policy_key(brand_id)))
        row.value_json = {**row.value_json, "public_reputation_risk_threshold": 0.5}
    notify.plan(factory, NIGHT)
    work = notify.claim_deliveries(factory, settings, NIGHT)
    assert len(work) == 1 and "公開留言聲譽風險" in work[0]["messages"][0]["text"]


def test_urgency_policy_change_and_no_text_excluded(setup, settings):
    factory, brand_id, _ = setup
    incoming(setup, at=NIGHT, urgency=0.7)
    incoming(setup, at=NIGHT, text="", urgency=1)
    notify.plan(factory, NIGHT)
    assert notify.claim_deliveries(factory, settings, NIGHT) == []
    with factory.begin() as session:
        row = session.scalar(select(Setting).where(Setting.key == notify.policy_key(brand_id)))
        row.value_json = {**row.value_json, "urgency_threshold": 0.65}
    notify.plan(factory, NIGHT)
    assert len(notify.claim_deliveries(factory, settings, NIGHT)) == 1


def test_retry_body_identity_backoff_expiry_and_wrong_lease(setup, settings):
    factory, _, clock = setup
    incoming(setup)
    notify.plan(factory, DAY)
    first = notify.claim_deliveries(factory, settings, DAY)[0]
    with pytest.raises(HTTPException) as error:
        notify.finish(factory, first["id"], DeliveryResult(lease_id=str(uuid4()), status_code=200))
    assert error.value.status_code == 409
    sent(factory, first, code=503)
    assert notify.claim_deliveries(factory, settings, DAY) == []
    second = notify.claim_deliveries(factory, settings, DAY + timedelta(minutes=1))[0]
    assert second["retry_key"] == first["retry_key"] and second["messages"] == first["messages"]
    assert second["lease_id"] != first["lease_id"]
    assert sent(factory, second, code=409, already=True) == {"status": "sent"}
    incoming(setup, at=DAY + timedelta(minutes=2))
    notify.plan(factory, DAY + timedelta(minutes=2))
    another = notify.claim_deliveries(factory, settings, DAY + timedelta(minutes=2))[0]
    later = notify.claim_deliveries(factory, settings, DAY + timedelta(hours=24))
    assert all(delivery["id"] != another["id"] for delivery in later)
    with factory() as session:
        assert session.get(NotificationDelivery, another["id"]).error == "retry_window_expired"


@pytest.mark.parametrize("code", [400, 401, 403, 409, 429])
def test_nonretryable_error_is_visible(setup, settings, code):
    incoming(setup)
    notify.plan(setup[0], DAY)
    work = notify.claim_deliveries(setup[0], settings, DAY)[0]
    assert sent(setup[0], work, code=code) == {"status": "failed"}
    assert notify.claim_deliveries(setup[0], settings, DAY + timedelta(hours=1)) == []


def test_fallback_and_model_failure_do_not_block_notifications(setup, settings, monkeypatch):
    factory, _, clock = setup
    thread, _ = incoming(setup, classified=False, text="電話0912345678，緊急客訴")

    def unavailable(*_args):
        raise HTTPException(503, "模型暫時無法使用")

    assert notify.dispatch(factory, settings)["deliveries"] == []
    clock[0] = DAY + timedelta(minutes=2)
    result = notify.dispatch(factory, settings)
    assert len(result["deliveries"]) == 1
    text = json.dumps(result, ensure_ascii=False)
    assert "0912345678" not in text and "REDACTED_PHONE" in text and "原生 App" in text
    assert (
        notify.emergency(
            "dm",
            classify.keyword("請立即點擊 http://test.invalid，否則停權", False),
            NotificationPolicy(),
        )
        is None
    )


def test_new_question_is_parallel_and_raw_preserved(settings, monkeypatch):
    expected = answer("complaint")
    expected["answers"]["public_reputation_risk"]["noul"] = 0.96
    calls = []
    settings.jev_api_key = SecretStr(secrets.token_urlsafe(32))

    def post(_url, _key, payload, _timeout):
        calls.append(payload)
        return 200, expected, 0

    monkeypatch.setattr(jev, "post_json", post)
    result, raw = classify.evaluate(
        "騙子公司，大家不要被騙", {"thread_kind": "comment_thread"}, settings
    )
    assert result.error is None and raw["signals"]["public_reputation_risk"] == 0.96
    assert len(calls) == 1 and len(calls[0]["questions"]) == 7
    assert raw["response"] == expected


def login(client, factory, role="admin"):
    password = SecretStr(secrets.token_urlsafe(24))
    with factory.begin() as session:
        staff = Staff(
            username=role, display_name="測試", role=role, password_hash=hash_password(password)
        )
        session.add(staff)
    client.headers.update(shared_login(client, role, password.get_secret_value()))


def test_notify_policy_auth_csrf_version_and_enable_boundary(setup, client, settings):
    factory, brand_id, clock = setup
    path = f"/api/notify/policy?brand_id={brand_id}"
    assert client.get(path).status_code == 401
    login(client, factory)
    original = client.get(path).json()
    change = {
        **NotificationPolicy(enabled=False).model_dump(),
        "group_id": original["group_id"],
        "version": original["version"],
    }
    assert client.put(path, json=change, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    result = client.put(path, json=change)
    assert result.status_code == 200
    assert client.put(path, json=change).status_code == 409
    old_thread, _ = incoming(setup, at=DAY - timedelta(hours=2))
    change.update(enabled=True, version=result.json()["version"])
    result = client.put(path, json=change)
    assert result.status_code == 200 and datetime.fromisoformat(result.json()["enabled_at"]) == DAY
    incoming(setup)
    notify.plan(factory, DAY)
    assert all(r.thread_id != old_thread for r in notices(setup))
    assert settings.notify_line_channel_access_token.get_secret_value() not in result.text


@pytest.mark.parametrize("role", ["viewer", "marketing"])
def test_policy_brand_permission(setup, client, role):
    login(client, setup[0], role)
    path = f"/api/notify/policy?brand_id={setup[1]}"
    assert client.get(path).status_code == 403
    assert (
        client.put(path, json={**NotificationPolicy().model_dump(), "version": 0}).status_code
        == 403
    )


def test_internal_endpoints_and_signed_group_discovery(setup, settings, client):
    # 派送只由排程直接呼叫 service；舊內部 dispatch／result 入口已移除。
    assert client.post("/api/notify/dispatch").status_code in {404, 405}
    assert client.post("/api/notify/deliveries/1/result").status_code in {404, 405}
    settings.notify_line_channel_secret = SecretStr(secrets.token_urlsafe(32))
    settings.notify_line_bot_user_id = "U" + secrets.token_hex(16)
    group = "C" + secrets.token_hex(16)
    raw = json.dumps(
        {
            "destination": settings.notify_line_bot_user_id,
            "events": [
                {"type": "join", "source": {"type": "group", "groupId": group}},
            ],
        }
    ).encode()
    signature = base64.b64encode(
        hmac.new(
            settings.notify_line_channel_secret.get_secret_value().encode(), raw, hashlib.sha256
        ).digest()
    ).decode()
    headers = {
        "X-API-Key": settings.ingest_api_key.get_secret_value(),
        "X-Line-Signature": signature,
    }
    assert (
        client.post("/api/notify/groups/events", content=raw + b" ", headers=headers).status_code
        == 401
    )
    assert client.post("/api/notify/groups/events", content=raw, headers=headers).status_code == 200
    assert client.post("/api/notify/groups/events", content=raw, headers=headers).status_code == 200
    assert client.get("/api/notify/groups").status_code == 401
    assert list(client.get("/api/notify/groups", headers=headers).json()["groups"]) == [group]
    with setup[0]() as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 0


def test_lost_callback_reclaims_same_payload(setup, settings):
    incoming(setup)
    notify.plan(setup[0], DAY)
    original = notify.claim_deliveries(setup[0], settings, DAY)[0]
    assert notify.claim_deliveries(setup[0], settings, DAY + timedelta(minutes=3)) == []
    recovered = notify.claim_deliveries(setup[0], settings, DAY + timedelta(minutes=4))[0]
    assert recovered["id"] == original["id"]
    assert recovered["retry_key"] == original["retry_key"]
    assert recovered["messages"] == original["messages"]


def test_digest_enforces_line_utf16_limit(setup, settings):
    for _ in range(20):
        incoming(setup, text="😀" * 400)
    notify.plan(setup[0], DAY)
    work = notify.claim_deliveries(setup[0], settings, DAY)[0]
    assert len(work["messages"]) <= 5
    assert all(len(m["text"].encode("utf-16-le")) // 2 <= 5000 for m in work["messages"])
    assert "另有 4 則" in "".join(m["text"] for m in work["messages"])
