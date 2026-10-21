"""Taipei calendar dates use inclusive start and exclusive next-day end in UTC."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.models.base import utc_now

DatePeriod = Literal["all", "7", "30", "90", "custom"]
TAIPEI = ZoneInfo("Asia/Taipei")


def date_bounds(
    period: DatePeriod = "all",
    date_from: date | None = None,
    date_to: date | None = None,
    *,
    now: datetime | None = None,
):
    if period in {"7", "30", "60", "90"}:
        date_to = (now or utc_now()).astimezone(TAIPEI).date()
        date_from = date_to - timedelta(days=int(period) - 1)
    elif period == "all" and date_from is None and date_to is None:
        return None, None
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "起日不可晚於迄日")
    if date_from == date.min:
        raise HTTPException(422, "起日超出支援範圍")
    if date_to == date.max:
        raise HTTPException(422, "迄日超出支援範圍")
    start = datetime.combine(date_from, time.min, TAIPEI).astimezone(UTC) if date_from else None
    end = (
        datetime.combine(date_to + timedelta(days=1), time.min, TAIPEI).astimezone(UTC)
        if date_to
        else None
    )
    return start, end


def comment_bounds(period="30", date_from=None, date_to=None, *, now=None):
    today = (now or utc_now()).astimezone(TAIPEI).date()
    if period == "custom" and (
        not date_from or not date_to or not date_from <= date_to <= today
    ):
        raise HTTPException(422, "留言起日與迄日必填，且起日 ≤ 迄日 ≤ 今天（台北）")
    return date_bounds(period, date_from, date_to, now=now)


def report_comment_bounds(report):
    data = report.data_json
    if not data.get("comment_range"):
        return report.start_at, report.end_at
    return (datetime.fromisoformat(data["comment_start"]),
            datetime.fromisoformat(data["comment_end"]))


def filter_dates(query, column, period="all", date_from=None, date_to=None):
    start, end = date_bounds(period, date_from, date_to)
    if start:
        query = query.where(column >= start)
    if end:
        query = query.where(column < end)
    return query
