import time
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select

from app.logging_config import log_failure
from app.models import AIRun
from app.schemas.ai import RETIRED_PROVIDERS, AISettings
from app.services import settings_store
from app.services.ai import providers
from app.services.ai_keys import resolve
from app.services.posts import _begin_ingest
from app.services.redact import redact

PROVIDERS = ("gemini_api", "openai_api", "anthropic_api")
UNPAID_REASON = (
    "Gemini 免費方案會將送出內容用於改善 Google 產品，不能處理留言等平台資料；"
    "請啟用付費方案並於本機 .env 設定 GEMINI_PAID_TIER=true"
)


def unpaid(provider, settings):
    # 平台條款要求服務供應商不得把資料用於自身目的；Gemini 免費額度做不到，故後端一律擋下。
    return provider == "gemini_api" and not settings.gemini_paid_tier


def options(settings, session=None):
    values = []
    for provider in PROVIDERS:
        model = getattr(settings, provider.replace("_api", "_model"))
        try:
            available = bool(resolve(provider, settings, session) and model)
        except HTTPException:
            available = False
        reason = None if available else "請至 AI 設定輸入 API 金鑰，並於本機 .env 指定模型"
        if available and unpaid(provider, settings):
            available, reason = False, UNPAID_REASON
        values.append(
            {"provider": provider, "model": model, "available": available, "reason": reason}
        )
    return values


def readable(values):
    # 退休的本機 CLI 設定值一律視為未設定；只在讀取時轉換，不改寫資料庫。
    return {
        key: None if isinstance(value, str) and value in RETIRED_PROVIDERS else value
        for key, value in values.items()
    }


def config(session, brand_id, settings):
    row = settings_store.get(session, f"ai.brand.{brand_id}")
    if row:
        return AISettings(**readable(row.value_json), version=row.version)
    default = "gemini_api"
    for provider in PROVIDERS:
        if unpaid(provider, settings):
            continue
        try:
            if resolve(provider, settings, session):
                default = provider
                break
        except HTTPException:
            continue
    return AISettings(
        manual_provider=default,
        background_provider=default,
        monthly_budget_usd=settings.ai_monthly_budget_usd,
    )


def background_provider(session, brand_id, settings):
    # 排程報告原本固定用 Gemini；未付費時改用品牌的背景供應者或第一個可用的 API，
    # 都沒有時仍回 Gemini，讓報告以 provider_unpaid_tier 明確失敗而不是默默改送他處。
    preferred = config(session, brand_id, settings).background_provider
    usable = [o["provider"] for o in options(settings, session) if o["available"]]
    if preferred in usable:
        return preferred
    return usable[0] if usable else "gemini_api"


def budget(session, brand_id, settings):
    local = datetime.now(ZoneInfo("Asia/Taipei"))
    start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    base = select(AIRun).where(
        AIRun.brand_id == brand_id, AIRun.mode == "api", AIRun.created_at >= start
    )
    rows = list(session.scalars(base))
    cost = sum((row.cost_usd or Decimal(0) for row in rows), Decimal(0))
    limit = config(session, brand_id, settings).monthly_budget_usd
    return {
        "estimated_usd": float(cost),
        "monthly_budget_usd": limit,
        "unknown_cost_runs": sum(row.cost_usd is None for row in rows),
        "warning": bool(limit and cost >= Decimal(str(limit)) * Decimal("0.8")),
        "exceeded": bool(limit and cost >= Decimal(str(limit))),
    }


def configuration_view(access, brand_id, settings):
    access.require_brand(brand_id)
    cfg = config(access.session, brand_id, settings)
    recent = access.session.scalars(
        access.statement(AIRun, brand_id).order_by(AIRun.id.desc()).limit(20)
    )
    return {
        "config": cfg.model_dump(),
        "options": options(settings, access.session),
        "budget": budget(access.session, brand_id, settings),
        "runs": [
            {
                "id": r.id,
                "task": r.task,
                "provider": r.provider,
                "model": r.model,
                "mode": r.mode,
                "trigger": r.trigger,
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
                "cost_usd": r.cost_usd,
                "ok": r.ok,
                "error": r.error,
                "duration_ms": r.duration_ms,
            }
            for r in recent
        ],
    }


def execution_options(access, brand_id, settings):
    access.require_brand(brand_id)
    cfg = config(access.session, brand_id, settings)
    return {
        "draft_provider": cfg.default_provider or "",
        "options": [
            {key: value[key] for key in ("provider", "model", "available")}
            for value in options(settings, access.session)
        ],
    }


def update_configuration(access, brand_id, body, settings):
    access.require_brand(brand_id, write=True)
    session, actor = access.session, f"staff:{access.staff.id}"
    session.commit()
    with session.begin():
        audit = _begin_ingest(session, "ai.settings")
        audit.actor, audit.brand_id = actor, brand_id
        row = settings_store.get(session, f"ai.brand.{brand_id}")
        settings_store.require_version(row, body.version, "設定已變更，請重新整理")
        values = body.model_dump(exclude={"version"})
        settings_store.put(session, f"ai.brand.{brand_id}", values, row)
        audit.detail_json = values
    return configuration_view(access, brand_id, settings)


def estimate(provider, model, tokens_in, tokens_out):
    if tokens_in is None or tokens_out is None:
        return None
    if provider == "jev" and model == "jev-1.13.0":
        return Decimal(tokens_in) * Decimal("0.000000042")
    if provider == "gemini_api" and model == "gemini-3.8-flash":
        # 2026-09-26 官方 Standard 付費牌價；未折抵免費額度、快取或帳單折扣。
        factor = 1 if datetime.now(UTC).year < 2027 else 2
        return (
            (Decimal(tokens_in) * Decimal("0.75") + Decimal(tokens_out) * Decimal("3.75"))
            * factor
            / 1_000_000
        )
    return None


def record(factory, task, brand_id, provider, trigger, result):
    with factory.begin() as session:
        session.add(
            AIRun(
                task=task,
                provider=provider,
                model=result.model or "unavailable",
                mode="api",
                trigger=trigger,
                brand_id=brand_id,
                ok=result.error is None,
                error=result.error_detail,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                duration_ms=result.duration_ms,
                cost_usd=estimate(provider, result.model, result.tokens_in, result.tokens_out),
            )
        )


def run(task, prompt, trigger, *, factory, settings, brand_id, provider, model="", staff_id=None):
    result = providers.Result(model=model)
    start = time.perf_counter()
    if trigger not in {"manual", "background"}:
        raise ValueError("未知觸發來源")
    if provider not in PROVIDERS:
        result.error = "provider_unavailable"
    elif unpaid(provider, settings):
        result.error = "provider_unpaid_tier"
    elif len(prompt) > 80000:
        result.error = "input_too_large"
    else:
        try:
            model = model or getattr(settings, provider.replace("_api", "_model"))
            result.model = model
            key = resolve(provider, settings)
            with factory() as session:
                exceeded = budget(session, brand_id, settings)["exceeded"]
                fallback = getattr(
                    config(session, brand_id, settings), provider.replace("_api", "_fallback_model")
                )
            if not key or not model:
                result.error = "configuration_missing"
            elif exceeded:
                result.error = "monthly_budget_exceeded"
            else:
                result = providers.call_api(
                    provider, model, redact(prompt).text, settings, fallback
                )
            if not result.error and not result.text.strip():
                result.error = "empty_output"
            if len(result.text) > 12000:
                result.text, result.error = result.text[:12000], "output_too_large"
            result.text = redact(result.text).text
        except Exception as error:
            log_failure("mwb.ai", "ai_run_failed", error)
            result.error = "provider_failed"
    result.duration_ms = round((time.perf_counter() - start) * 1000)
    record(factory, task, brand_id, provider, trigger, result)
    return result
