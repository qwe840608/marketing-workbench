"""Audience breakdowns: one latest copy per account, refreshed daily by the metrics job.

Only official read APIs are used (Graph insights, Threads insights, YouTube Analytics reports);
reads served to the browser come from the local DB and never call a platform.
"""

from datetime import UTC, datetime, time

from sqlalchemy import func, select

from app.models import Account, AudienceInsight
from app.models.base import utc_now
from app.services.date_ranges import TAIPEI

METRICS = ("followers", "viewers", "online")
BREAKDOWNS = ("age", "gender", "country", "city", "hour")
# 平台自己的人口統計分群，原樣保存；地區只留前幾名，避免長尾撐大資料列。
TOP_LOCATIONS = 10


def today_start(now):
    return datetime.combine(now.astimezone(TAIPEI).date(), time.min, TAIPEI).astimezone(UTC)


def registered(session, platform, external_id):
    rows = list(
        session.scalars(
            select(Account.id)
            .where(Account.platform == platform, Account.external_id == external_id)
            .limit(2)
        )
    )
    return rows[0] if len(rows) == 1 else None


def due(session, account_id, now=None):
    """當天（台北）已經存過一份就不再抓；失敗不寫入，所以下一輪會重試。"""
    now = now or utc_now()
    latest = session.scalar(
        select(func.max(AudienceInsight.fetched_at)).where(AudienceInsight.account_id == account_id)
    )
    return latest is None or latest < today_start(now)


def clean(items, limit=None):
    rows = [
        {"key": str(row["key"])[:64], "value": row["value"]}
        for row in items
        if isinstance(row.get("value"), int | float) and row["value"] >= 0
    ]
    rows.sort(key=lambda row: (-row["value"], row["key"]))
    return rows[:limit] if limit else rows


def save(factory, account_id, rows, now=None):
    """同一帳號的各項一次寫入：只有整批都拿到結果才覆寫，避免新舊資料混在一起。"""
    now = now or utc_now()
    with factory.begin() as session:
        existing = {
            (row.metric, row.breakdown): row
            for row in session.scalars(
                select(AudienceInsight).where(AudienceInsight.account_id == account_id)
            )
        }
        for value in rows:
            if value["metric"] not in METRICS or value["breakdown"] not in BREAKDOWNS:
                raise ValueError("unknown_audience_row")
            row = existing.get((value["metric"], value["breakdown"]))
            if row is None:
                row = AudienceInsight(
                    account_id=account_id, metric=value["metric"], breakdown=value["breakdown"]
                )
                session.add(row)
            row.status = "ready" if value.get("items") else "unavailable"
            row.error = None if value.get("items") else value.get("error") or "no_data"
            row.period = value["period"]
            row.unit = value.get("unit", "count")
            row.items_json = value.get("items") or []
            row.fetched_at = now
    return len(rows)


def view(access, brand_id=None):
    if brand_id is not None:
        access.require_brand(brand_id)
    accounts = list(
        access.session.scalars(
            access.statement(Account, brand_id).order_by(Account.platform, Account.id)
        )
    )
    if not accounts:
        return {"timezone": "Asia/Taipei", "accounts": []}
    rows = {}
    for row in access.session.scalars(
        select(AudienceInsight)
        .where(AudienceInsight.account_id.in_([a.id for a in accounts]))
        .order_by(AudienceInsight.id)
    ):
        rows.setdefault(row.account_id, []).append(
            {
                "metric": row.metric,
                "breakdown": row.breakdown,
                "status": row.status,
                "error": row.error,
                "period": row.period,
                "unit": row.unit,
                "items": row.items_json,
                "fetched_at": row.fetched_at,
            }
        )
    return {
        "timezone": "Asia/Taipei",
        "accounts": [
            {
                "id": account.id,
                "brand_id": account.brand_id,
                "platform": account.platform,
                "name": account.name,
                "status": account.status,
                "insights": rows.get(account.id, []),
            }
            for account in accounts
        ],
    }
