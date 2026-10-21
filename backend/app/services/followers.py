"""Follower reads use local observations only; missing days are never fabricated."""

from calendar import monthrange
from datetime import UTC, date, datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from app.models import Account, FollowerSnapshot
from app.models.base import utc_now
from app.services.date_ranges import TAIPEI
from app.services.posts import _begin_ingest, require_account


def due(session, platform, external_id, now=None):
    now = now or utc_now()
    account = require_account(session, platform, external_id)
    start = datetime.combine(now.astimezone(TAIPEI).date(), time.min, TAIPEI).astimezone(UTC)
    latest = session.scalar(
        select(FollowerSnapshot.id)
        .where(
            FollowerSnapshot.account_id == account.id,
            FollowerSnapshot.captured_at >= start,
            FollowerSnapshot.captured_at <= now,
        )
        .limit(1)
    )
    return {"due": latest is None}


def record(session, body):
    with session.begin():
        _begin_ingest(session, "ingest.followers")
        account = require_account(session, body.platform, body.account_external_id)
        if body.captured_at > utc_now() + timedelta(minutes=1):
            raise HTTPException(422, "快照時間不可在未來")
        result = session.execute(
            insert(FollowerSnapshot)
            .values(
                account_id=account.id,
                captured_at=body.captured_at,
                followers_count=body.followers_count,
            )
            .on_conflict_do_nothing(index_elements=["account_id", "captured_at"])
        )
        return {"inserted": result.rowcount}


def observation(row):
    return {"captured_at": row.captured_at, "followers_count": row.followers_count}


def period_delta(session, account_id, start, end):
    query = select(FollowerSnapshot).where(FollowerSnapshot.account_id == account_id)
    rows = list(
        session.scalars(
            query.where(
                FollowerSnapshot.captured_at >= start,
                FollowerSnapshot.captured_at < end,
            ).order_by(FollowerSnapshot.captured_at)
        )
    )
    baseline = session.scalar(
        query.where(
            FollowerSnapshot.captured_at <= start,
        )
        .order_by(FollowerSnapshot.captured_at.desc())
        .limit(1)
    )
    if baseline is None and rows:
        baseline = rows[0]
    daily = {}
    for row in rows:
        day = row.captured_at.astimezone(TAIPEI).date()
        daily[day] = row
    # No observations in the requested period means unknown, rather than zero growth.
    latest = next(reversed(daily.values())) if daily else None
    return latest.followers_count - baseline.followers_count if latest and baseline else None


def month_weeks(year, month):
    start = date(year, month, 1)
    last = date(year, month, monthrange(year, month)[1])
    weeks = []
    while start <= last:
        end = min(start + timedelta(days=6 - start.weekday()), last)
        weeks.append({"week": len(weeks) + 1, "date_from": start, "date_to": end})
        start = end + timedelta(days=1)
    return weeks


def view(
    access, platform, brand_id=None, year=None, month=None, week=None, account_id=None, now=None
):
    now = now or utc_now()
    today = now.astimezone(TAIPEI).date()
    year, month = year or today.year, month or today.month
    if not 1 <= year <= 9998 or not 1 <= month <= 12:
        raise HTTPException(422, "年月無效")
    weeks = month_weeks(year, month)
    current_weeks = month_weeks(today.year, today.month)
    current_week = next(w["week"] for w in current_weeks if w["date_from"] <= today <= w["date_to"])
    is_current_month = (year, month) == (today.year, today.month)
    week = week if week is not None else current_week if is_current_month else 1
    if not 1 <= week <= len(weeks):
        raise HTTPException(422, "該月份沒有此週次")
    selected = weeks[week - 1]
    query = access.statement(Account, brand_id).where(Account.platform == platform)
    if account_id is not None:
        query = query.where(Account.id == account_id)
    accounts = list(access.session.scalars(query.order_by(Account.id)))
    years = {today.year}
    result = []

    def delta(account, start, end):
        start = datetime.combine(start, time.min, TAIPEI).astimezone(UTC)
        end = datetime.combine(end + timedelta(days=1), time.min, TAIPEI).astimezone(UTC)
        return period_delta(
            access.session, account.id, start, min(end, now + timedelta(microseconds=1))
        )

    for account in accounts:
        query = select(FollowerSnapshot).where(
            FollowerSnapshot.account_id == account.id,
            FollowerSnapshot.captured_at <= now,
        )
        years.update(
            stamp.astimezone(TAIPEI).year
            for stamp in access.session.scalars(
                select(FollowerSnapshot.captured_at).where(
                    FollowerSnapshot.account_id == account.id, FollowerSnapshot.captured_at <= now
                )
            )
        )
        latest = access.session.scalar(query.order_by(FollowerSnapshot.captured_at.desc()).limit(1))
        result.append(
            {
                "account_id": account.id,
                "platform": account.platform,
                "name": account.name,
                "current": observation(latest) if latest else None,
                "week_delta": delta(account, selected["date_from"], selected["date_to"]),
                "month_delta": delta(account, date(year, month, 1), weeks[-1]["date_to"]),
            }
        )

    def total(values):
        return sum(values) if values and all(v is not None for v in values) else None

    hidden = False
    if platform == "youtube":
        from app.services import oauth

        connection = oauth.connection(access.session, "youtube")
        hidden = bool(connection and connection.cache_json.get("subscriber_hidden"))
    return {
        "subscriber_hidden": hidden,
        "platform": platform,
        "connected": bool(accounts),
        "years": sorted(years, reverse=True),
        "year": year,
        "month": month,
        "week": week,
        "weeks": weeks,
        "is_current_month": is_current_month,
        "is_current_week": is_current_month and week == current_week,
        "current_count": None if hidden else total(
            [a["current"]["followers_count"] if a["current"] else None for a in result]
        ),
        "week_delta": None if hidden else total([a["week_delta"] for a in result]),
        "month_delta": None if hidden else total([a["month_delta"] for a in result]),
        "accounts": result,
    }
