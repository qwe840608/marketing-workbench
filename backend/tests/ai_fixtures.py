"""Shared synthetic AI data for marketing feature tests."""

import secrets

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from test_classify import classified_data as classified_data

from app.models import Message
from app.services import jev, video_scripts
from app.services.ai import providers


def historical_draft(client, data):
    from httpx import Response

    from app.models import Draft

    with client.app.state.session_factory.begin() as session:
        row = Draft(
            thread_id=data["thread_id"],
            text="historical fixture",
            provider="gemini_api",
            model="test",
        )
        session.add(row)
        session.flush()
        return Response(200, json={"id": row.id})


def review_response(failed=None):
    return {
        "model": "jev-1.13.0",
        "answers": {
            key: {"type": "noul", "noul": 0.9 if key == failed else 0.01}
            for key in video_scripts.CHECKS
        },
        "usage": {"input_tokens": 400, "output_tokens": 30},
    }


@pytest.fixture
def ai_data(client, settings, classified_data, monkeypatch):
    settings.gemini_api_key = SecretStr(secrets.token_urlsafe(32))
    # 測試資料代表已綁定帳單的付費方案；未付費的擋下行為另有測試。
    settings.gemini_paid_tier = True
    settings.gemini_model = "gemini-3.8-flash"
    settings.jev_api_key = SecretStr(secrets.token_urlsafe(32))
    with client.app.state.session_factory() as session:
        message = session.scalar(select(Message).where(Message.external_id == "test:message:3"))
        thread_id = message.thread_id
        classified_data = {**classified_data, "message_id": message.id}
    monkeypatch.setattr(
        providers,
        "call_api",
        lambda *a: providers.Result(
            "請提供服務需求類型與照片，專人將協助確認服務方式。", "gemini-3.8-flash", 200, 80
        ),
    )
    monkeypatch.setattr(jev, "post_json", lambda *a: (200, review_response(), 0))
    return {**classified_data, "thread_id": thread_id}
