from collections import Counter
from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import aliased, selectinload

from app.models import Account, Classification, Message, MetricSnapshot, Post, Thread
from app.models.base import utc_now
from app.services import classify

TAIPEI = ZoneInfo("Asia/Taipei")
# 漏斗最後一階「消費詢問」採計的分類：問價、預約、問服務內容；客訴、合作、求職不算。
INQUIRY_INTENTS = ("price", "booking", "model_question")


def incoming_messages(access, brand_id, start, now, *, before=None):
    # 平台 ID 的唯一約束在入庫時去重；摘要與趨勢共用同一計數範圍。
    # before 給前期比較用：前期終點不含，避免剛好在邊界的留言同時算進兩期。
    return access.statement(Message, brand_id).where(
        Thread.kind == "comment_thread",
        Message.direction == "in",
        Message.author_type == "fan",
        Message.sent_at >= start,
        Message.sent_at < before if before is not None else Message.sent_at <= now,
    )


def count(access, statement):
    return access.session.scalar(select(func.count()).select_from(statement.subquery()))


def latest_classification():
    return (
        select(Classification.id)
        .where(Classification.message_id == Message.id)
        .order_by(Classification.id.desc())
        .limit(1)
        .correlate(Message)
        .scalar_subquery()
    )


def valid_intents(access, statement, intents):
    """逐則回傳最新且指紋仍有效的分類；留言改過字之後的舊分類不算。"""
    latest = aliased(Classification)
    for message, classification, kind in access.session.execute(
        statement.join(latest, latest.id == latest_classification())
        .where(latest.intent.in_(intents))
        .with_only_columns(Message, latest, Thread.kind)
    ):
        context = classify.input_context(kind)
        if classification.input_hash == classify.fingerprint(message.text, context):
            yield classification.intent


def latest_snapshot(now):
    return (
        select(MetricSnapshot.id)
        .where(
            MetricSnapshot.post_id == Post.id,
            MetricSnapshot.captured_at <= now,
        )
        .order_by(MetricSnapshot.captured_at.desc(), MetricSnapshot.id.desc())
        .limit(1)
        .correlate(Post)
        .scalar_subquery()
    )


def window(access, brand_id, days, now):
    if days not in (7, 30):
        raise HTTPException(422, "天數只能為 7 或 30")
    if brand_id is not None:
        access.require_brand(brand_id)
    today = now.astimezone(TAIPEI).replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=days - 1)


def trends(access, brand_id=None, days=30, now=None):
    now = now or utc_now()
    start = window(access, brand_id, days, now)
    rows = {
        (start + timedelta(days=i)).date().isoformat(): {
            "date": (start + timedelta(days=i)).date().isoformat(),
            "new_messages": 0,
        }
        for i in range(days)
    }
    # 一次批次 SELECT（含前一段等長期間）；自然日分組在記憶體處理，避免 SQLite 時區／逐日查詢。
    previous = 0
    for sent in access.session.scalars(
        incoming_messages(
            access, brand_id, (start - timedelta(days=days)).astimezone(UTC), now
        ).with_only_columns(Message.sent_at)
    ):
        if sent < start:
            previous += 1
        else:
            rows[sent.astimezone(TAIPEI).date().isoformat()]["new_messages"] += 1
    # previous_total＝前一段等長期間（例如前 30 天）的總數，供「比前期」；0 時前端不算百分比。
    return {
        "days": days,
        "timezone": "Asia/Taipei",
        "series": list(rows.values()),
        "previous_total": previous,
    }


def funnel(access, brand_id=None, days=30, now=None):
    """近 N 天發佈、有觸及數據的貼文：觸及 → 互動 → 留言 → 消費詢問。"""
    now = now or utc_now()
    start = window(access, brand_id, days, now).astimezone(UTC)
    metrics = aliased(MetricSnapshot)
    rows = access.session.execute(
        access.statement(Post, brand_id)
        .where(Post.deleted_at.is_(None), Post.published_at >= start, Post.published_at <= now)
        .join(metrics, metrics.id == latest_snapshot(now))
        .where(metrics.reach.is_not(None))
        .with_only_columns(
            Post.id, metrics.reach, metrics.likes, metrics.comments, metrics.shares, metrics.saves
        )
    ).all()
    ids = [row[0] for row in rows]
    # 互動是次數（同一人可按讚又留言），所以可能大於觸及人數；前端照實顯示不截斷。
    engagement = sum(sum(value or 0 for value in row[2:]) for row in rows)
    comments = access.statement(Message, brand_id).where(
        Thread.kind == "comment_thread",
        Thread.post_id.in_(ids),
        Message.direction == "in",
        Message.author_type == "fan",
        Message.sent_at <= now,
    )
    return {
        "days": days,
        "timezone": "Asia/Taipei",
        "posts": len(ids),
        "stages": [
            {"key": "reach", "value": sum(row[1] for row in rows)},
            {"key": "engagement", "value": engagement},
            {"key": "comments", "value": count(access, comments) if ids else 0},
            {
                "key": "inquiries",
                "value": sum(1 for _ in valid_intents(access, comments, INQUIRY_INTENTS))
                if ids
                else 0,
            },
        ],
    }


def summary(access, brand_id, now=None):
    if brand_id is not None:
        access.require_brand(brand_id)
    now = now or utc_now()
    local = now.astimezone(ZoneInfo("Asia/Taipei"))
    start = (
        (local - timedelta(days=local.weekday()))
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .astimezone(UTC)
    )
    incoming = incoming_messages(access, brand_id, start, now)
    total = count(access, incoming)
    # 上週同期：上週一 00:00 到七天前的此刻，與本週期間等長。
    previous = count(
        access,
        incoming_messages(
            access, brand_id, start - timedelta(days=7), now, before=now - timedelta(days=7)
        ),
    )
    latest_class = latest_classification()
    latest = aliased(Classification)
    intents = access.session.execute(
        incoming.outerjoin(latest, latest.id == latest_class)
        .with_only_columns(latest.intent, func.count())
        .group_by(latest.intent)
        .order_by(func.count().desc(), latest.intent)
    ).all()

    # 與分流共用輸入定義；只統計最新且指紋仍有效的分類。
    valid = Counter(valid_intents(access, incoming, set(classify.INTENTS) - {"spam"}))
    top = sorted(valid.items(), key=lambda item: (-item[1], item[0]))

    snapshot = latest_snapshot(now)
    metrics = aliased(MetricSnapshot)
    ranked = (
        access.statement(Post, brand_id)
        .where(Post.published_at >= start, Post.published_at <= now)
        .join(metrics, metrics.id == snapshot)
        .where(metrics.reach.is_not(None))
        .add_columns(Account.platform, metrics.reach, metrics.captured_at)
        .options(selectinload(Post.thumbnail))
    )

    def posts(order):
        return [
            {
                "id": p.id,
                "caption": p.caption,
                "platform": platform,
                "reach": reach,
                "captured_at": captured,
                "permalink": p.permalink,
                "thumbnail_url": p.thumbnail_url,
            }
            for p, platform, reach, captured in access.session.execute(
                ranked.order_by(order, Post.id).limit(3)
            )
        ]

    return {
        "week_start": start,
        "as_of": now,
        "new_messages": total,
        "new_comments": total,
        "previous": {
            "start": start - timedelta(days=7),
            "end": now - timedelta(days=7),
            "new_comments": previous,
        },
        "top_intent": {"intent": top[0][0], "count": top[0][1]} if top else None,
        "intents": [{"intent": intent or "unclassified", "count": n} for intent, n in intents],
        "highest_reach": posts(metrics.reach.desc()),
        "lowest_reach": posts(metrics.reach.asc()),
    }
