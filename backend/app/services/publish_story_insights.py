"""Hourly live IG story snapshots and signed final values; no dashboard aggregation."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import Account, PublishPost, PublishStorySnapshot, PublishTarget
from app.models.base import utc_now
from app.services import credentials

METRICS = ("views", "reach", "replies", "shares", "navigation", "follows", "profile_visits")
LEGACY = ("impressions", "exits", "taps_forward", "taps_back")


def counts(value):
    return {
        key: number
        for key, number in value.items()
        if key in METRICS + LEGACY and type(number) is int and 0 <= number <= 9007199254740991
    }


def store(session, target_id, position, at, metrics, *, final=False):
    slot = "final" if final else at.strftime("%Y-%m-%dT%H")
    row = session.scalar(
        select(PublishStorySnapshot).where(
            PublishStorySnapshot.target_id == target_id,
            PublishStorySnapshot.position == position,
            PublishStorySnapshot.slot == slot,
        )
    )
    if row:
        if at >= row.observed_at:
            row.metrics_json = {**row.metrics_json, **counts(metrics)}
            row.observed_at = at
    else:
        session.add(
            PublishStorySnapshot(
                target_id=target_id,
                position=position,
                slot=slot,
                observed_at=at,
                final=final,
                metrics_json=counts(metrics),
            )
        )


def results(session, target):
    snapshots = list(
        session.scalars(
            select(PublishStorySnapshot)
            .where(
                PublishStorySnapshot.target_id == target.id,
            )
            .order_by(PublishStorySnapshot.final, PublishStorySnapshot.observed_at)
        )
    )
    result = []
    for story in target.detail_json.get("stories", []):
        rows = [row for row in snapshots if row.position == story["position"]]
        metrics = {}
        for row in rows:
            metrics.update(row.metrics_json)
        result.append(
            {
                "position": story["position"],
                "media_id": story["media_id"],
                "platform_post_id": story["platform_post_id"],
                "published_at": story["published_at"],
                "metrics": metrics,
                "final": any(row.final for row in rows),
                "snapshots": [
                    {
                        "observed_at": row.observed_at,
                        "final": row.final,
                        "metrics": row.metrics_json,
                    }
                    for row in rows
                ],
            }
        )
    return result


def hourly(factory, settings, workers, now=None):
    now = now or utc_now()
    slot = now.strftime("%Y-%m-%dT%H")
    due = []
    with factory() as session:
        current = credentials.raw(credentials.resolve("META_IG_ACCOUNT_ID", settings, session))
        token = credentials.raw(credentials.resolve("META_PAGE_ACCESS_TOKEN", settings, session))
        if not current or not token:
            return {"snapshots": 0, "errors": 0}
        query = (
            select(PublishTarget)
            .join(PublishPost)
            .join(Account, Account.id == PublishTarget.account_id)
            .where(
                PublishPost.format == "story",
                PublishTarget.platform == "instagram",
                Account.external_id == current,
            )
        )
        for target in session.scalars(query):
            for story in target.detail_json.get("stories", []):
                at = datetime.fromisoformat(story["published_at"])
                rows = list(
                    session.scalars(
                        select(PublishStorySnapshot).where(
                            PublishStorySnapshot.target_id == target.id,
                            PublishStorySnapshot.position == story["position"],
                        )
                    )
                )
                if not at <= now < at + timedelta(hours=24) or any(row.final for row in rows):
                    continue
                # 以整點時段判斷：排程抖動讓這小時比上小時早幾分鐘跑，也不能跳過這一格。
                if any(not row.final and row.slot == slot for row in rows):
                    continue
                due.append((target.id, story["position"], story["platform_post_id"]))
    result = {"snapshots": 0, "errors": 0}
    context = {"platform": "instagram", "account_external_id": current, "source": "metrics"}
    from app.services.publish_platforms import safe_id

    for target_id, position, identity in due:
        try:

            def read(names, total=False, identity=identity):
                query = {"metric": ",".join(names), "period": "lifetime"}
                if total:
                    query["metric_type"] = "total_value"
                response = workers.graph(safe_id(identity) + "/insights", query, context)
                body = response.get("body") or {}
                error = body.get("error")
                if response["statusCode"] != 200 or error:
                    return None, error.get("code") if isinstance(error, dict) else None
                metrics = {}
                for row in body.get("data", []):
                    if not isinstance(row, dict):
                        continue
                    values, total = row.get("values"), row.get("total_value")
                    value = total.get("value") if isinstance(total, dict) else None
                    if isinstance(values, list) and values and isinstance(values[0], dict):
                        value = values[0].get("value")
                    metrics.update(counts({row.get("name"): value}))
                return metrics, None

            metrics, code = read(METRICS)
            if code == 100:
                # 平台對某限動可能不提供全部指標；逐項讀取保留有效值，缺值不補零。
                metrics = {}
                for name in METRICS:
                    values, error = read((name,))
                    if error == 100:
                        values, error = read((name,), total=True)
                    if error not in (None, 100):
                        break
                    metrics.update(values or {})
            if not metrics:
                result["errors"] += 1
                continue
            with factory.begin() as session:
                store(session, target_id, position, now, metrics)
            result["snapshots"] += 1
        except Exception:
            # 不保存供應商原文；共享 graph 配額或權限錯誤留待下次排程。
            result["errors"] += 1
    return result


def webhook(session, envelope):
    entry = envelope["payload"]["entry"][0]
    event = entry["changes"][0]
    value = event.get("value")
    if not isinstance(value, dict) or not isinstance(value.get("media_id"), (str, int)):
        raise ValueError("Invalid story insights")
    at = datetime.fromtimestamp(entry["time"], UTC)
    metrics = counts(value)
    if not metrics:
        return
    query = (
        select(PublishTarget)
        .join(PublishPost)
        .join(Account, Account.id == PublishTarget.account_id)
        .where(
            PublishPost.format == "story",
            PublishTarget.platform == "instagram",
            Account.external_id == envelope["account_external_id"],
        )
    )
    for target in session.scalars(query):
        story = next(
            (
                s
                for s in target.detail_json.get("stories", [])
                if s["platform_post_id"] == str(value["media_id"])
            ),
            None,
        )
        if story:
            store(session, target.id, story["position"], at, metrics, final=True)
            session.flush()
            return
