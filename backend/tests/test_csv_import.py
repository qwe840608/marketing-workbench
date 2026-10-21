import base64
import csv
import io
import json
import secrets
from datetime import UTC, datetime

import pytest
from conftest import login as shared_login
from pydantic import SecretStr
from sqlalchemy import func, select

from app.models import (
    Account,
    AIRun,
    AuditLog,
    Brand,
    Draft,
    InboundJob,
    Message,
    Notification,
    RawEvent,
    Staff,
    Thread,
)
from app.schemas.ingest import ContactInput, MessageInput
from app.services import ingest, jev
from app.services.csv_import import safe_cell
from app.services.passwords import hash_password

HEADERS = [
    "platform",
    "brand",
    "kind",
    "external_id",
    "conversation_id",
    "created_at",
    "author",
    "content",
    "source_url",
    "source_ref",
]


def csv_text(rows, headers=HEADERS):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows(rows)
    return stream.getvalue()


def row(identity="csv-1", text="[隔離] 服務詢問", **changes):
    data = dict(
        zip(
            HEADERS,
            [
                "FB",
                "csv-test",
                "comment_thread",
                identity,
                "conversation-1",
                "2026-09-20 09:30:00",
                "測試客人",
                text,
                "https://example.com/message",
                "test.csv:2",
            ],
            strict=True,
        )
    )
    data.update(changes)
    return [data[h] for h in HEADERS]


@pytest.fixture
def csv_data(client):
    password = SecretStr(secrets.token_urlsafe(24))
    with client.app.state.session_factory.begin() as session:
        staff = Staff(
            username="csv-admin",
            display_name="隔離管理員",
            role="admin",
            password_hash=hash_password(password),
        )
        brand = Brand(slug="csv-test", name="[隔離] CSV")
        other = Brand(slug="csv-other", name="[隔離] 其他")
        session.add_all([staff, brand, other])
        session.flush()
        account = Account(
            brand_id=brand.id, platform="facebook", external_id="csv-account", name="CSV 測試帳號"
        )
        another = Account(
            brand_id=other.id, platform="facebook", external_id="other-account", name="另一帳號"
        )
        session.add_all([account, another])
        session.flush()
        ids = dict(
            brand=brand.id, other=other.id, account=account.id, another=another.id, staff=staff.id
        )
    client.headers.update(shared_login(client, "csv-admin", password.get_secret_value()))
    return ids


def upload(client, ids, content=None, raw=None):
    raw = raw if raw is not None else (content or csv_text([row()])).encode("utf-8-sig")
    return client.post(
        "/api/csv/preview",
        json={
            "brand_id": ids["brand"],
            "filename": "歷史.csv",
            "content_base64": base64.b64encode(raw).decode(),
        },
    )


def validate(client, ids, preview, columns=None, accounts=None):
    return client.post(
        "/api/csv/validate",
        json={
            "token": preview["token"],
            "columns": columns or {c["column"]: c["field"] for c in preview["columns"]},
            "accounts": accounts if accounts is not None else {"facebook": ids["account"]},
        },
    )


def confirm(client, preview, validated):
    return client.post(
        "/api/csv/confirm", json={"token": preview["token"], "revision": validated["revision"]}
    )


def test_legacy_csv_preview_confirm_timezone_dedup_errors_and_no_jobs(client, csv_data):
    content = csv_text(
        [
            row(),
            row(),
            row("bad", created_at="錯誤時間"),
            row("comment", kind="comment", conversation_id="post-1"),
            row("formula", text='  =HYPERLINK("bad")'),
        ]
    )
    preview = upload(client, csv_data, content).json()
    assert all(c["field"] for c in preview["columns"])
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 0
    checked = validate(client, csv_data, preview)
    assert checked.status_code == 200, checked.text
    data = checked.json()
    assert data["valid"] == 4 and data["errors"][0]["row"] == 4
    assert data["samples"][-1]["text"].startswith("'  =")
    result = confirm(client, preview, data)
    assert result.status_code == 200, result.text
    assert result.json()["created"] == 3 and result.json()["duplicates"] == 1
    assert confirm(client, preview, data).json() == result.json()
    second = upload(client, csv_data, content).json()
    again = confirm(client, second, validate(client, csv_data, second).json()).json()
    assert again["created"] == 0 and again["duplicates"] == 4
    with client.app.state.session_factory() as session:
        messages = list(session.scalars(select(Message).order_by(Message.id)))
        assert all(m.is_historical and m.sources_json == ["csv"] for m in messages)
        assert messages[0].sent_at == datetime(2026, 9, 20, 1, 30, tzinfo=UTC)
        assert messages[-1].text == '  =HYPERLINK("bad")'
        for model in (InboundJob, Draft, Notification):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        assert not session.get(Account, csv_data["account"]).send_enabled
        assert session.scalar(select(func.count()).select_from(RawEvent)) == 3
        raw = session.scalar(select(RawEvent).order_by(RawEvent.id))
        assert (
            raw.payload_json["message"]["source_ref_json"]["csv_original_time"]
            == "2026-09-20 09:30:00"
        )
        audit = session.scalar(select(AuditLog).where(AuditLog.action == "csv.import"))
        assert audit.actor == f"staff:{csv_data['staff']}"


def test_renamed_columns_jev_payload_redacted_low_confidence_manual(
    client, csv_data, settings, monkeypatch
):
    settings.jev_api_key = SecretStr("isolated-test-key")
    fields = [
        "platform",
        "kind",
        "external_id",
        "thread_id",
        "sent_at",
        "author",
        "text",
        "source_url",
    ]
    observed = []

    def stub(_url, _key, payload, _timeout):
        observed.append(payload)
        answers = {}
        for index, field in enumerate(fields):
            question = payload["questions"][str(index)]
            assert question["type"] == "choice" and "ignore" in question["criteria"]
            answers[str(index)] = {
                "type": "choice",
                "choice": field,
                "confidence": 0.5 if index == 5 else 0.99,
                "probabilities": {k: float(k == field) for k in question["criteria"]},
            }
        return (
            200,
            {
                "model": "jev-1.13.0",
                "answers": answers,
                "usage": {"input_tokens": 120, "output_tokens": 20},
            },
            0,
        )

    monkeypatch.setattr(jev, "post_json", stub)
    headers = [f"欄位{x}" for x in range(8)]
    content = csv_text(
        [
            [
                "FB",
                "comment_thread",
                "renamed-1",
                "c-1",
                "2026-09-20T09:30:00+08:00",
                "test@example.com",
                "電話 0912345678 地址信義路100號",
                "https://example.com",
            ]
        ],
        headers,
    )
    preview = upload(client, csv_data, content).json()
    assert len(observed) == 1
    payload = json.dumps(observed, ensure_ascii=False)
    assert (
        "0912345678" not in payload and "test@example.com" not in payload and "100號" not in payload
    )
    assert preview["columns"][5]["field"] is None
    assert preview["columns"][5]["confidence"] == 0.5
    mapping = {str(i): field for i, field in enumerate(fields)}
    data = validate(client, csv_data, preview, columns=mapping).json()
    assert confirm(client, preview, data).json()["created"] == 1
    with client.app.state.session_factory() as session:
        run = session.scalar(select(AIRun).where(AIRun.task == "csv_mapping"))
        assert run.tokens_in == 120 and run.cost_usd is not None


def test_missing_key_unknown_header_requires_manual_mapping(client, csv_data, monkeypatch):
    monkeypatch.setattr(jev, "post_json", lambda *args: pytest.fail("不應連外"))
    headers = [*HEADERS[:-1], "陌生欄位"]
    preview = upload(client, csv_data, csv_text([row()], headers)).json()
    assert preview["fallback"] and preview["columns"][-1]["field"] is None
    mapping = {c["column"]: c["field"] for c in preview["columns"] if c["field"]}
    assert validate(client, csv_data, preview, columns=mapping).status_code == 422
    mapping["9"] = "ignore"
    data = validate(client, csv_data, preview, columns=mapping).json()
    assert confirm(client, preview, data).json()["created"] == 1


def test_existing_webhook_duplicate_different_thread_and_conflict_do_not_overwrite(
    client, csv_data
):
    with client.app.state.session_factory.begin() as session:
        account = session.get(Account, csv_data["account"])
        source = MessageInput(
            external_id="csv-1",
            thread_external_id="official-thread",
            kind="comment_thread",
            contact=ContactInput(external_id="official-fan"),
            direction="in",
            author_type="fan",
            text="[隔離] 服務詢問",
            sent_at="2026-09-20T01:30:00Z",
        )
        contact = ingest._contact(session, account, source)
        thread = ingest._thread(session, account, contact, source)
        ingest._message(session, contact, thread, source, source.sent_at, "webhook", source.sent_at)
    preview = upload(client, csv_data, csv_text([row(), row(text="衝突"), row("valid")])).json()
    result = confirm(client, preview, validate(client, csv_data, preview).json()).json()
    assert result["created"] == 1 and result["duplicates"] == 1 and len(result["errors"]) == 1
    with client.app.state.session_factory() as session:
        existing = session.scalar(select(Message).where(Message.external_id == "csv-1"))
        assert existing.text == "[隔離] 服務詢問" and not existing.is_historical
        assert existing.sources_json == ["csv", "webhook"]
        assert session.scalar(select(func.count()).select_from(Thread)) == 2


@pytest.mark.parametrize(
    "raw,status",
    [
        (b"", 422),
        (b"\xff\xfe", 422),
        (b"a,a\n1,2", 422),
        (b"a\n\x00", 422),
        (b'a\n"unclosed', 422),
        (b"a" * (2 * 1024 * 1024 + 1), 422),
        (("a\n" + "1\n" * 5001).encode(), 413),
    ],
    ids=["empty", "encoding", "duplicate_headers", "nul", "quotes", "oversize", "too_many_rows"],
)
def test_file_limits_and_encoding(client, csv_data, raw, status):
    response = upload(client, csv_data, raw=raw)
    # Base64 schema can reject an oversized file before decoding.
    assert response.status_code in ({413, 422} if len(raw) > 2 * 1024 * 1024 else {status})


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"brand": "csv-other"}, "品牌"),
        ({"created_at": "2040-01-01"}, "未來"),
        ({"source_url": "javascript:alert(1)"}, "網址"),
        ({"external_id": "bad id"}, "ID"),
        ({"content": "x" * 20001}, "20000"),
        ({"content": ""}, "空白"),
        ({"platform": "unknown"}, "平台"),
        ({"kind": "out"}, "類型"),
    ],
)
def test_bad_rows_do_not_interrupt_good_rows(client, csv_data, changes, reason):
    preview = upload(client, csv_data, csv_text([row("bad", **changes), row("good")])).json()
    checked = validate(client, csv_data, preview).json()
    assert checked["valid"] == 1 and reason in checked["errors"][0]["reason"]
    result = confirm(client, preview, checked).json()
    assert result["created"] == 1 and len(result["errors"]) == 1


def test_preview_binding_permissions_csrf_and_revision(client, csv_data):
    preview = upload(client, csv_data).json()
    assert (
        validate(client, csv_data, preview, accounts={"facebook": csv_data["another"]}).status_code
        == 422
    )
    checked = validate(client, csv_data, preview).json()
    newer = validate(client, csv_data, preview).json()
    assert confirm(client, preview, checked).status_code == 409
    token = client.headers.pop("X-CSRF-Token")
    assert confirm(client, preview, newer).status_code == 403
    client.headers["X-CSRF-Token"] = token
    with client.app.state.session_factory.begin() as session:
        session.get(Staff, csv_data["staff"]).role = "viewer"
    assert confirm(client, preview, newer).status_code == 403


def test_preview_expiration_and_owner_binding(client, csv_data):
    preview = upload(client, csv_data).json()
    value = client.app.state.csv_import_store.items[preview["token"]]
    value.staff_id += 1
    assert validate(client, csv_data, preview).status_code == 404
    value.staff_id -= 1
    value.expires = 0
    assert validate(client, csv_data, preview).status_code == 404


@pytest.mark.parametrize("value", ["=1+1", "+SUM(1)", "-1", "@cmd", "\t=1", "  ＝1"])
def test_formula_guard(value):
    assert safe_cell(value).startswith("'")


def test_large_cell_is_row_error_not_whole_file_failure(client, csv_data):
    preview = upload(client, csv_data, csv_text([row("huge", text="x" * 140000), row("ok")])).json()
    checked = validate(client, csv_data, preview).json()
    assert checked["valid"] == 1 and "20000" in checked["errors"][0]["reason"]
    assert confirm(client, preview, checked).json()["created"] == 1


def test_account_changed_after_preview_is_rejected(client, csv_data):
    preview = upload(client, csv_data).json()
    checked = validate(client, csv_data, preview).json()
    with client.app.state.session_factory.begin() as session:
        session.get(Account, csv_data["account"]).platform = "instagram"
    result = confirm(client, preview, checked).json()
    assert result["created"] == 0 and len(result["errors"]) == 1


def test_missing_conversation_and_source_use_explicit_csv_provenance(client, csv_data):
    preview = upload(
        client, csv_data, csv_text([row(conversation_id="", source_url="", source_ref="")])
    ).json()
    checked = validate(client, csv_data, preview).json()
    assert "第 2 列" in checked["samples"][0]["source_ref"]
    assert confirm(client, preview, checked).json()["created"] == 1
    with client.app.state.session_factory() as session:
        thread = session.scalar(select(Thread))
        assert thread.external_id.startswith("csv:")
        assert "source_url" not in thread.source_ref_json


def test_marketing_cannot_upload_another_brand(client, csv_data):
    with client.app.state.session_factory.begin() as session:
        session.get(Staff, csv_data["staff"]).role = "marketing"
    assert upload(client, csv_data).status_code == 403
