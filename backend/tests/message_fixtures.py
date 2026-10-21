"""Synthetic messages and platform events; no send implementation."""

import json
import secrets

import pytest
from ai_fixtures import review_response
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select

from app.models import (
    Account,
    Brand,
    Classification,
    Contact,
    LineReplyCredential,
    Message,
    Staff,
    StaffBrand,
    Thread,
)
from app.models.base import utc_now
from app.services import ai_keys, ingest, jev
from app.services.ai import providers
from app.services.passwords import hash_password


@pytest.fixture
def send_data(client, settings, monkeypatch):
    factory = client.app.state.session_factory
    password = secrets.token_urlsafe(24)
    settings.account_encryption_key = SecretStr(Fernet.generate_key().decode())
    settings.meta_page_access_token = SecretStr(secrets.token_urlsafe(32))
    settings.jev_api_key = SecretStr(secrets.token_urlsafe(32))
    settings.gemini_api_key = SecretStr(secrets.token_urlsafe(32))
    settings.gemini_paid_tier = True
    settings.gemini_model = "gemini-3.8-flash"
    with factory.begin() as s:
        from brand_fixtures import FORBIDDEN

        from app.services.branding import put_setting

        put_setting(s, "brand.rules.1", {"forbidden_phrases": FORBIDDEN})
        b = Brand(slug="demo", name="隔離驗收品牌", marketing_dm_enabled=True)
        s.add(b)
        s.flush()
        staff = Staff(
            username="send-admin",
            display_name="隔離送出者",
            role="admin",
            password_hash=hash_password(SecretStr(password)),
        )
        a = Account(
            brand_id=b.id,
            platform="facebook",
            external_id="10001",
            name="隔離測試帳號",
            token_ref="META_PAGE_ACCESS_TOKEN",
            send_enabled=True,
        )
        c = Contact(
            brand_id=b.id, platform="facebook", external_id="20001", display_name="隔離客人"
        )
        s.add_all([staff, a, c])
        s.flush()
        s.add(StaffBrand(staff_id=staff.id, brand_id=b.id))
        t = Thread(
            brand_id=b.id,
            account_id=a.id,
            contact_id=c.id,
            external_id=c.external_id,
            kind="dm",
            last_inbound_at=utc_now(),
        )
        s.add(t)
        s.flush()
        m = Message(
            thread_id=t.id,
            contact_id=c.id,
            external_id="incoming-1",
            direction="in",
            author_type="fan",
            text="請問服務流程？",
            sent_at=t.last_inbound_at,
        )
        s.add(m)
        s.flush()
        s.add(
            Classification(
                message_id=m.id,
                engine="jev",
                intent="other",
                sentiment="neutral",
                sensitive=False,
                action="human",
                confidence=0.99,
            )
        )
        ids = {
            "thread": t.id,
            "account": a.id,
            "brand": b.id,
            "staff": staff.id,
            "message": m.id,
            "contact": c.id,
        }
    bootstrap = client.get("/api/auth/csrf").json()["csrf_token"]
    login = client.post(
        "/api/auth/login",
        json={"username": "send-admin", "password": password},
        headers={"origin": "http://testserver", "x-csrf-token": bootstrap},
    )
    assert login.status_code == 200
    csrf = client.get("/api/auth/csrf").json()["csrf_token"]
    client.headers.update({"origin": "http://testserver", "x-csrf-token": csrf})
    calls = []

    monkeypatch.setattr(jev, "post_json", lambda *a: (200, review_response(), 0))
    monkeypatch.setattr(
        providers,
        "call_api",
        lambda *a: providers.Result(
            "請提供需求類型照片，由專人說明服務流程。", "gemini-3.8-flash", 200, 80
        ),
    )
    return {**ids, "calls": calls, "factory": factory}


def change(d, model, id_key, **values):
    with d["factory"].begin() as s:
        row = s.get(model, d[id_key])
        for k, v in values.items():
            setattr(row, k, v)


def classify_as(d, value):
    with d["factory"].begin() as s:
        s.scalar(select(Classification)).action = value


def line(d, settings):
    change(d, Account, "account", platform="line", token_ref="LINE_CHANNEL_ACCESS_TOKEN")
    with d["factory"].begin() as s:
        s.add(
            LineReplyCredential(
                message_id=d["message"],
                encrypted_token=ai_keys.cipher(settings).encrypt(b"private-reply-token").decode(),
                received_at=utc_now(),
            )
        )


def echo(d, settings, mid="mid.outgoing"):
    body = {
        "platform": "facebook",
        "account_external_id": "10001",
        "external_id": "echo-" + mid,
        "signature_ok": True,
        "payload": {},
        "messages": [
            {
                "external_id": mid,
                "thread_external_id": "20001",
                "kind": "dm",
                "contact": {"external_id": "20001"},
                "direction": "out",
                "author_type": "brand",
                "text": "您好，專人將為您說明服務流程。",
                "sent_at": utc_now().isoformat(),
            }
        ],
    }
    with d["factory"]() as s:
        return ingest.events(s, json.dumps(body).encode(), settings=settings)
