import copy
import json
import secrets
from datetime import timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from test_classify import answer
from test_classify import classified_data as classified_data

from app.models import AIRun, Draft, Message
from app.models.base import utc_now
from app.schemas.classify import Policy
from app.services import classify, jev
from app.services.ai import providers
from app.services.redact import redact


@pytest.mark.parametrize("text", ["", " \n\t", "[貼圖]", "[Sticker]", "[圖片]"])
def test_no_text_skips_without_any_model_or_draft(client, classified_data, monkeypatch, text):
    monkeypatch.setattr(jev, "ask", lambda *a: pytest.fail("無文字不應呼叫 jev"))
    monkeypatch.setattr(providers, "call_api", lambda *a: pytest.fail("無文字不應產生草稿"))
    mid = classified_data["message_id"]
    factory = client.app.state.session_factory
    with factory.begin() as session:
        row = session.get(Message, mid)
        row.text, row.sent_at = text, utc_now() + timedelta(minutes=1)
        thread_id = row.thread_id
    result = client.post(f"/api/classifications/messages/{mid}")
    assert result.status_code == 200, result.text
    assert result.json()["engine"] == "policy"
    assert result.json()["action"] == "skip"
    assert result.json()["raw"]["response"] is None
    draft = client.post(f"/api/drafts/threads/{thread_id}", json={"provider": "gemini_api"})
    assert draft.status_code == 404
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AIRun)) == 0
        assert session.scalar(select(func.count()).select_from(Draft)) == 0


@pytest.mark.parametrize("noul", [0.0, 0.45, 0.5, 1.0])
def test_personal_data_is_audit_only(noul):
    signals = classify.signals(answer("booking"))
    signals["contains_personal_data"] = noul
    assert classify.decide(signals, Policy(), pii=True) == ("classified", False, [])
    signals["wants_human"] = 1
    assert classify.decide(signals, Policy(), pii=True)[0] == "classified"


@pytest.mark.parametrize(
    "text,secret,kind",
    [
        ("我的 LINE ID 是 test_line_01，方便加我聊嗎", "test_line_01", "line_id"),
        ("LINE ID: ABC_def.01", "ABC_def.01", "line_id"),
        ("我的賴是 test_line_01", "test_line_01", "line_id"),
        ("https://line.me/ti/p/~test_line_01", "test_line_01", "line_id"),
        ("電話0912-000-123", "0912-000-123", "phone"),
        ("住台中市西屯區測試路10號", "測試路10號", "address"),
        ("Email demo@example.com", "demo@example.com", "email"),
        ("身分證A123456789", "A123456789", "id"),
    ],
)
def test_redaction_required_fields(text, secret, kind):
    masked = redact(text)
    assert secret not in masked.text
    assert masked.counts[kind] == 1
    assert redact(masked.text).text == masked.text


@pytest.mark.parametrize(
    "intent,text",
    [
        ("job", "請問有徵人嗎"),
        ("reschedule", "預約取消訂單"),
        ("reschedule", "明天預約改到下週三"),
    ],
)
def test_new_intents_always_human_in_model_and_fallback(intent, text):
    assert classify.keyword(text, False)["intent"] == intent
    values = classify.signals(answer(intent))
    assert classify.decide(values, Policy(confidence_threshold=0))[:2] == ("classified", False)


def test_pii_audit_response_preserved_and_draft_payload_scrubbed(
    client, classified_data, settings, monkeypatch
):
    settings.jev_api_key = SecretStr(secrets.token_urlsafe(32))
    settings.gemini_api_key = SecretStr(secrets.token_urlsafe(32))
    settings.gemini_model = "gemini-3.8-flash"
    from ai_fixtures import review_response

    raw = answer("other")
    raw["answers"]["contains_personal_data"]["noul"] = 0.99
    recorded = copy.deepcopy(raw)

    def transport(url, key, payload, timeout):
        assert "test_line_01" not in json.dumps(payload)
        return 200, raw if "intent" in payload["questions"] else review_response(), 0

    monkeypatch.setattr(jev, "post_json", transport)
    prompts = []
    monkeypatch.setattr(
        providers,
        "call_api",
        lambda p, m, text, s, fallback="": (
            prompts.append(text) or providers.Result("可以在這裡告訴我們需求。", m, 10, 10)
        ),
    )
    mid = classified_data["message_id"]
    with client.app.state.session_factory.begin() as session:
        msg = session.get(Message, mid)
        msg.text = "我的 LINE ID 是 test_line_01，方便加我聊嗎"
        msg.sent_at = utc_now() + timedelta(minutes=1)
        thread_id = msg.thread_id
    result = client.post(f"/api/classifications/messages/{mid}").json()
    assert result["action"] == "classified" and result["contains_personal_data"]
    assert result["raw"]["response"] == recorded
    assert (
        client.post(f"/api/drafts/threads/{thread_id}", json={"provider": "gemini_api"}).status_code
        == 404
    )
    assert prompts == []
