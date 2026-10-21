import base64
import copy
import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from conftest import deliver_event
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select

from app.config import Settings
from app.models import (
    Account,
    Brand,
    Contact,
    InboundJob,
    Message,
    Post,
    RawEvent,
    Thread,
)
from app.models.base import utc_now
from app.services import data_retention, ingest


@pytest.fixture
def ingest_data(client, settings):
    key = SecretStr(secrets.token_urlsafe(32))
    settings.ingest_api_key = key
    with client.app.state.session_factory.begin() as session:
        first = Brand(slug="ingest-demo", name="[測試] TEST")
        second = Brand(slug="ingest-other", name="[測試] 其他品牌")
        session.add_all([first, second])
        session.flush()
        accounts = []
        for index, brand in enumerate([first, second]):
            account = Account(
                brand_id=brand.id,
                platform="facebook",
                external_id=f"test-account-{index}",
                name="[測試] API 隔離帳號",
                status="disconnected",
            )
            session.add(account)
            session.flush()
            accounts.append(account.id)
        ids = {"brand": first.id, "other_brand": second.id, "accounts": accounts}
    return {"key": key, **ids}


@pytest.fixture
def event():
    return {
        "platform": "facebook",
        "account_external_id": "test-account-0",
        "external_id": "test-event-1",
        "signature_ok": True,
        "payload": {"events": [{"id": "test-message-1", "text": "[測試] 詢問服務方式"}]},
        "messages": [
            {
                "external_id": "test-message-1",
                "thread_external_id": "test-thread-1",
                "kind": "comment_thread",
                "contact": {"external_id": "test-contact-1", "display_name": "測試聯絡人"},
                "direction": "in",
                "author_type": "fan",
                "text": "[測試] 詢問服務方式",
                "sent_at": "2026-09-26T09:00:00+08:00",
            }
        ],
    }


def send(client, data, event):
    return deliver_event(client, event)


def counts(client):
    with client.app.state.session_factory() as session:
        return {
            model.__tablename__: session.scalar(select(func.count()).select_from(model))
            for model in (Contact, Thread, Message, RawEvent, InboundJob)
        }


def test_duplicate_event_preserves_versions_and_queues_once(client, ingest_data, event):
    first = send(client, ingest_data, event)
    assert first.status_code == 200
    assert first.json()["created_messages"] == 1
    assert first.json()["queued_jobs"] == 2
    with client.app.state.session_factory() as session:
        versions = [session.scalar(select(model)).version for model in (Contact, Thread, Message)]
    second = send(client, ingest_data, event)
    assert second.status_code == 200
    assert second.json()["raw_event_id"] == first.json()["raw_event_id"]
    assert second.json()["unchanged_messages"] == 1
    assert second.json()["queued_jobs"] == 0
    assert counts(client) == {
        "contacts": 1,
        "threads": 1,
        "messages": 1,
        "raw_events": 1,
        "inbound_jobs": 2,
    }
    with client.app.state.session_factory() as session:
        assert [
            session.scalar(select(model)).version for model in (Contact, Thread, Message)
        ] == versions
        raw = session.scalar(select(RawEvent))
        assert raw.payload_json == event["payload"]
        assert raw.processed and raw.signature_ok and raw.error is None
        assert raw.brand_id == ingest_data["brand"]
        assert {job.task for job in session.scalars(select(InboundJob))} == {"classify", "notify"}
        assert all(job.status == "pending" for job in session.scalars(select(InboundJob)))
        assert session.scalar(select(Message)).sent_at == datetime(2026, 9, 26, 1, tzinfo=UTC)


def test_resent_event_after_retention_does_not_recreate_comments(client, ingest_data, event):
    first = send(client, ingest_data, event)
    assert first.json()["created_messages"] == 1
    later = utc_now() + timedelta(days=400)
    data_retention.prune(client.app.state.session_factory, client.app.state.settings, later)
    assert counts(client)["messages"] == 0
    with client.app.state.session_factory() as session:
        raw = session.scalar(select(RawEvent))
        assert raw.payload_json == {} and raw.error == data_retention.REMOVED_EVENT
    # 平台重送同一事件：留下的平台 ID 讓它被視為已處理，不重建留言、聯絡人或通知。
    again = send(client, ingest_data, event)
    assert again.status_code == 200
    assert again.json()["raw_event_id"] == first.json()["raw_event_id"]
    assert again.json()["processed"] and again.json()["created_messages"] == 0
    assert counts(client) == {
        "contacts": 0,
        "threads": 0,
        "messages": 0,
        "raw_events": 1,
        "inbound_jobs": 0,
    }
    with client.app.state.session_factory() as session:
        assert session.scalar(select(RawEvent)).payload_json == {}
    # 已清除的事件不會每天被重新計入。
    assert (
        data_retention.preview(client.app.state.session_factory, client.app.state.settings, later)[
            "raw_events"
        ]
        == 0
    )


def test_duplicate_inside_batch_and_different_event_id(client, ingest_data, event):
    event["messages"].append(copy.deepcopy(event["messages"][0]))
    response = send(client, ingest_data, event)
    assert response.json()["created_messages"] == 1
    assert response.json()["unchanged_messages"] == 1
    event["external_id"] = "second-delivery-id"
    assert send(client, ingest_data, event).json()["created_messages"] == 0
    assert counts(client)["messages"] == 1
    assert counts(client)["raw_events"] == 2
    assert counts(client)["inbound_jobs"] == 2


def test_concurrent_redelivery_is_idempotent(client, ingest_data, event):
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: send(client, ingest_data, event), range(8)))
    assert [res.status_code for res in responses] == [200] * 8
    assert sum(res.json()["created_messages"] for res in responses) == 1
    assert counts(client)["messages"] == 1
    assert counts(client)["inbound_jobs"] == 2


def test_message_edit_updates_content_without_new_jobs(client, ingest_data, event, monkeypatch):
    # 固定首次收件時間，避免舊編輯保護讓測試結果隨執行日期改變。
    monkeypatch.setattr(ingest, "utc_now", lambda: datetime(2026, 9, 26, 1, tzinfo=UTC))
    assert send(client, ingest_data, event).status_code == 200
    event["messages"][0].update(
        text="[測試] 改為詢問預約",
        attachments_json=[{"type": "image", "external_id": "test-image"}],
        edited_at="2026-09-26T02:00:00Z",
    )
    response = send(client, ingest_data, event)
    assert response.status_code == 200
    assert response.json()["updated_messages"] == 1
    assert response.json()["queued_jobs"] == 0
    with client.app.state.session_factory() as session:
        message = session.scalar(select(Message))
        assert message.text == "[測試] 改為詢問預約"
        assert message.version == 2
        assert message.edited_at == datetime(2026, 9, 26, 2, tzinfo=UTC)
    assert send(client, ingest_data, event).json()["unchanged_messages"] == 1
    event["messages"][0].update(text="[測試] 舊編輯重送", edited_at="2026-09-26T01:30:00Z")
    assert send(client, ingest_data, event).json()["unchanged_messages"] == 1
    assert counts(client)["inbound_jobs"] == 2


def test_edit_without_timestamp_uses_receipt_time(client, ingest_data, event):
    send(client, ingest_data, event)
    event["messages"][0]["text"] = "[測試] 編輯沒有提供時間"
    assert send(client, ingest_data, event).json()["updated_messages"] == 1
    with client.app.state.session_factory() as session:
        assert (
            session.scalar(select(Message)).edited_at
            == session.scalar(select(RawEvent)).received_at
        )


def test_newer_edit_with_same_content_prevents_older_edit_overwrite(
    client, ingest_data, event, monkeypatch
):
    monkeypatch.setattr(ingest, "utc_now", lambda: datetime(2026, 9, 26, 1, tzinfo=UTC))
    send(client, ingest_data, event)
    event["messages"][0]["edited_at"] = "2026-09-26T03:00:00Z"
    assert send(client, ingest_data, event).json()["updated_messages"] == 1
    event["messages"][0].update(text="[測試] 延遲抵達的舊編輯", edited_at="2026-09-26T02:00:00Z")
    assert send(client, ingest_data, event).json()["unchanged_messages"] == 1
    with client.app.state.session_factory() as session:
        assert session.scalar(select(Message)).text == "[測試] 詢問服務方式"


REMOVED_INTERNAL_ROUTES = [
    ("POST", "/api/ingest/events"),
    ("POST", "/api/ingest/posts"),
    ("POST", "/api/ingest/metrics"),
    ("GET", "/api/ingest/metrics/due?platform=instagram&account_external_id=test-account-0"),
    ("POST", "/api/ingest/comments/events"),
    ("POST", "/api/ingest/comments/claim"),
    ("POST", "/api/ingest/comments/checkpoint"),
    ("POST", "/api/ingest/comments/finish"),
    ("POST", "/api/ingest/meta/calls/start"),
    ("POST", "/api/ingest/meta/calls/finish"),
    ("POST", "/api/classifications/dispatch"),
    ("POST", "/api/ideation/tick"),
    ("POST", "/api/notify/dispatch"),
    ("POST", "/api/notify/deliveries/1/result"),
]


@pytest.mark.parametrize("method,path", REMOVED_INTERNAL_ROUTES)
def test_worker_only_internal_routes_are_gone_even_with_key(
    client, ingest_data, event, method, path
):
    # Workers 直接呼叫 service；這些 HTTP 入口已移除，帶有效金鑰也不能寫入任何資料。
    response = client.request(
        method, path, json=event, headers={"X-Api-Key": ingest_data["key"].get_secret_value()}
    )
    assert response.status_code in {404, 405}
    assert all(value == 0 for value in counts(client).values())


@pytest.mark.parametrize("signature,status", [(False, 403), ("true", 422), (1, 422)])
def test_bad_verification_result_is_retained_but_never_ingested(
    client, ingest_data, event, signature, status
):
    event["signature_ok"] = signature
    assert send(client, ingest_data, event).status_code == status
    assert counts(client)["messages"] == 0
    with client.app.state.session_factory() as session:
        raw = session.scalar(select(RawEvent))
        assert not raw.signature_ok and not raw.processed and raw.error


@pytest.mark.parametrize("body", [b'{"broken":', b"\xff\x00", b'{"bad":NaN}'])
def test_unparseable_json_is_preserved_losslessly(client, ingest_data, body):
    response = deliver_event(client, body)
    assert response.status_code == 422
    with client.app.state.session_factory() as session:
        raw = session.scalar(select(RawEvent))
        assert raw.platform is None
        assert base64.b64decode(raw.payload_json["invalid_json_base64"]) == body
        assert raw.error == "invalid_payload"


@pytest.mark.parametrize("bad", [None, [], {"platform": "not-supported"}])
def test_json_with_invalid_envelope_is_retained(client, ingest_data, bad):
    response = deliver_event(client, json.dumps(bad).encode())
    assert response.status_code == 422
    with client.app.state.session_factory() as session:
        assert session.scalar(select(RawEvent)).payload_json == bad


def test_bad_message_schema_keeps_original_payload(client, ingest_data, event):
    event["messages"][0]["sent_at"] = "2026-09-26T09:00:00"
    response = send(client, ingest_data, event)
    assert response.status_code == 422
    with client.app.state.session_factory() as session:
        assert session.scalar(select(RawEvent)).payload_json == event["payload"]
    assert counts(client)["contacts"] == 0


def test_failed_batch_rolls_back_domain_writes_but_keeps_raw(
    client, ingest_data, event, monkeypatch
):
    original = ingest._message

    def conflict(session, contact, thread, source, *args):
        if source.external_id == "test-message-2":
            raise ingest.InvalidEvent("conversation_contact_conflict")
        return original(session, contact, thread, source, *args)

    monkeypatch.setattr(ingest, "_message", conflict)
    second = copy.deepcopy(event["messages"][0])
    second["external_id"] = "test-message-2"
    second["contact"]["external_id"] = "different-dm-peer"
    event["messages"].append(second)
    response = send(client, ingest_data, event)
    assert response.status_code == 422
    assert response.json()["error"] == "conversation_contact_conflict"
    assert counts(client) == {
        "contacts": 0,
        "threads": 0,
        "messages": 0,
        "raw_events": 1,
        "inbound_jobs": 0,
    }
    with client.app.state.session_factory() as session:
        raw = session.scalar(select(RawEvent))
        assert raw.brand_id == ingest_data["brand"]
        assert raw.error == "conversation_contact_conflict"


def test_internal_failure_keeps_raw_and_hides_exception_details(
    client, ingest_data, event, monkeypatch, settings
):
    private = SecretStr(secrets.token_urlsafe(32))
    original = ingest._process

    def fail_after_writes(*args):
        original(*args)
        raise RuntimeError(private.get_secret_value())

    monkeypatch.setattr(ingest, "_process", fail_after_writes)
    response = send(client, ingest_data, event)
    assert response.status_code == 503
    assert response.json()["error"] == "processing_failed"
    assert counts(client)["messages"] == 0
    with client.app.state.session_factory() as session:
        assert session.scalar(select(RawEvent)).error == "processing_failed"
    for value in (private, ingest_data["key"]):
        if value.get_secret_value() in response.text + settings.log_path.read_text(
            encoding="utf-8"
        ):
            pytest.fail("回應或日誌包含敏感值")


def test_unknown_account_can_be_registered_and_retried(client, ingest_data, event):
    event["account_external_id"] = "new-test-account"
    first = send(client, ingest_data, event)
    assert first.status_code == 422
    with client.app.state.session_factory.begin() as session:
        session.add(
            Account(
                brand_id=ingest_data["brand"],
                platform="facebook",
                external_id="new-test-account",
                name="[測試] 新帳號",
            )
        )
    second = send(client, ingest_data, event)
    assert second.status_code == 200
    assert second.json()["raw_event_id"] == first.json()["raw_event_id"]
    with client.app.state.session_factory() as session:
        assert session.scalar(select(RawEvent)).error is None


def test_ambiguous_account_is_rejected_without_guessing_brand(client, ingest_data, event):
    with client.app.state.session_factory.begin() as session:
        session.add(
            Account(
                brand_id=ingest_data["other_brand"],
                platform="facebook",
                external_id=event["account_external_id"],
                name="[測試] 重複設定",
            )
        )
    assert send(client, ingest_data, event).json()["error"] == "account_ambiguous"
    assert counts(client)["messages"] == 0


def test_same_external_ids_stay_isolated_between_brands(client, ingest_data, event):
    assert send(client, ingest_data, event).status_code == 200
    event["account_external_id"] = "test-account-1"
    assert send(client, ingest_data, event).status_code == 200
    assert counts(client) == {
        "contacts": 2,
        "threads": 2,
        "messages": 2,
        "raw_events": 2,
        "inbound_jobs": 4,
    }
    with client.app.state.session_factory() as session:
        for message in session.scalars(select(Message)):
            thread = session.get(Thread, message.thread_id)
            contact = session.get(Contact, message.contact_id)
            assert thread.brand_id == contact.brand_id


def test_caller_cannot_choose_brand(client, ingest_data, event):
    event["brand_id"] = ingest_data["other_brand"]
    assert send(client, ingest_data, event).status_code == 422
    assert counts(client)["messages"] == 0


def test_comment_thread_keeps_each_fans_contact_and_unresolved_post(client, ingest_data, event):
    first = event["messages"][0]
    first.update(kind="comment_thread", post_external_id="not-yet-synced-post")
    second = copy.deepcopy(first)
    second["contact"]["external_id"] = "test-commenter-2"
    second["external_id"] = "test-comment-2"
    event["messages"].append(second)
    assert send(client, ingest_data, event).status_code == 200
    with client.app.state.session_factory() as session:
        thread = session.scalar(select(Thread))
        assert thread.post_id is None
        assert thread.source_ref_json["post_external_id"] == "not-yet-synced-post"
        assert len({m.contact_id for m in session.scalars(select(Message))}) == 2
        assert session.scalar(select(func.count()).select_from(Post)) == 0


def test_source_reference_cannot_replace_a_threads_post(client, ingest_data, event):
    source = event["messages"][0]
    source.update(kind="comment_thread", post_external_id="first-post")
    assert send(client, ingest_data, event).status_code == 200
    source.update(post_external_id="other-post", source_ref_json={"post_external_id": "other-post"})
    assert send(client, ingest_data, event).json()["error"] == "conversation_post_conflict"
    with client.app.state.session_factory() as session:
        assert session.scalar(select(Thread)).source_ref_json["post_external_id"] == "first-post"


def test_standalone_referral_keeps_source_without_fake_message(client, ingest_data, event):
    referral = {**event, "messages": [], "references": [{"kind": "dm"}]}
    assert send(client, ingest_data, referral).status_code == 410
    assert all(v == 0 for v in counts(client).values())
    assert send(client, ingest_data, event).status_code == 200
    assert counts(client)["messages"] == 1


def test_untyped_source_reference_cannot_choose_a_post(client, ingest_data, event):
    event["messages"][0]["source_ref_json"] = {"post_external_id": "test-post"}
    assert send(client, ingest_data, event).status_code == 422
    assert counts(client)["messages"] == 0


def test_echo_and_late_inbound_preserve_latest_times_and_manual_fields(client, ingest_data, event):
    assert send(client, ingest_data, event).status_code == 200
    with client.app.state.session_factory.begin() as session:
        thread = session.scalar(select(Thread))
        thread.stage = "booked"
        thread.list_color = "green"
    message = event["messages"][0]
    message.update(
        external_id="outbound-echo",
        direction="out",
        author_type="brand",
        sent_at="2026-09-26T02:00:00Z",
    )
    assert send(client, ingest_data, event).json()["queued_jobs"] == 0
    message.update(
        external_id="late-old-message",
        direction="in",
        author_type="fan",
        sent_at="2026-09-26T00:00:00Z",
    )
    assert send(client, ingest_data, event).status_code == 200
    with client.app.state.session_factory() as session:
        thread = session.scalar(select(Thread))
        assert thread.last_inbound_at == datetime(2026, 9, 26, 1, tzinfo=UTC)
        assert thread.status == "replied"
        assert thread.stage == "booked" and thread.list_color == "green"
    message.update(external_id="new-inbound", sent_at="2026-09-26T03:00:00Z")
    assert send(client, ingest_data, event).status_code == 200
    with client.app.state.session_factory() as session:
        assert session.scalar(select(Thread)).status == "pending"


def test_oversized_request_is_rejected_before_retention(client, settings, ingest_data):
    # 大小上限現在只保護仍保留的內部原始位元組入口（LINE 通知群組探索）。
    settings.ingest_max_bytes = 1024
    response = client.post(
        "/api/notify/groups/events",
        content=b"x" * 1025,
        headers={"X-Api-Key": ingest_data["key"].get_secret_value()},
    )
    assert response.status_code == 413
    assert counts(client)["raw_events"] == 0


def test_short_ingest_key_is_rejected_without_disclosure():
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, ingest_api_key="too-short")
    assert "too-short" not in str(error.value)
