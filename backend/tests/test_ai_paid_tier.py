"""Gemini 免費方案不處理平台資料：選單不可選、後端執行一律擋下、排程改用可用的付費供應者。

全部使用合成資料與假 HTTP，不呼叫任何真實 AI。
"""

import secrets

from ai_fixtures import ai_data as ai_data
from ai_fixtures import classified_data as classified_data
from pydantic import SecretStr
from sqlalchemy import select

from app.models import AIRun
from app.services import ai
from app.services.ai import providers


def test_unpaid_gemini_is_unavailable_and_blocked_before_any_call(client, ai_data, monkeypatch):
    settings, brand_id = client.app.state.settings, ai_data["brand_id"]
    settings.gemini_paid_tier = False
    calls = []
    monkeypatch.setattr(providers, "call_api", lambda *a: calls.append(a))

    options = client.get(f"/api/ai/execution-options?brand_id={brand_id}").json()["options"]
    gemini = next(item for item in options if item["provider"] == "gemini_api")
    assert gemini["available"] is False
    view = client.get(f"/api/ai/settings?brand_id={brand_id}").json()
    reason = next(item for item in view["options"] if item["provider"] == "gemini_api")["reason"]
    assert "GEMINI_PAID_TIER" in reason

    factory = client.app.state.session_factory
    result = ai.run(
        "ideation",
        "留言原文",
        "manual",
        factory=factory,
        settings=settings,
        brand_id=brand_id,
        provider="gemini_api",
    )
    assert result.error == "provider_unpaid_tier"
    assert calls == []
    with factory() as session:
        run = session.scalars(select(AIRun).order_by(AIRun.id.desc())).first()
        assert (run.provider, run.ok, run.tokens_in) == ("gemini_api", False, None)


def test_paid_gemini_runs_normally(client, ai_data):
    settings, brand_id = client.app.state.settings, ai_data["brand_id"]
    assert settings.gemini_paid_tier is True
    result = ai.run(
        "ideation",
        "留言原文",
        "manual",
        factory=client.app.state.session_factory,
        settings=settings,
        brand_id=brand_id,
        provider="gemini_api",
    )
    assert result.error is None


def test_background_choice_skips_unpaid_gemini(client, ai_data):
    settings, brand_id = client.app.state.settings, ai_data["brand_id"]
    factory = client.app.state.session_factory
    settings.gemini_paid_tier = False
    with factory() as session:
        # 只有 Gemini 金鑰：排程仍回 Gemini，報告會以 provider_unpaid_tier 明確失敗。
        assert ai.background_provider(session, brand_id, settings) == "gemini_api"
    settings.openai_api_key = SecretStr(secrets.token_urlsafe(32))
    settings.openai_model = "test-model"
    with factory() as session:
        assert ai.background_provider(session, brand_id, settings) == "openai_api"
        assert ai.config(session, brand_id, settings).background_provider == "openai_api"
    settings.gemini_paid_tier = True
    with factory() as session:
        assert ai.background_provider(session, brand_id, settings) == "gemini_api"
