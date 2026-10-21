from datetime import UTC, date, datetime, timedelta

import pytest
from ai_fixtures import ai_data as ai_data
from sqlalchemy import select
from test_classify import classified_data as classified_data

from app.models import (
    Account,
    Brand,
    Contact,
    Message,
    MetricSnapshot,
    Post,
    Staff,
    StaffBrand,
    Thread,
)
from app.models.base import utc_now
from app.services import dashboard


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/settings/brand?brand_id=1"),
        ("put", "/api/settings/brand?brand_id=1"),
        ("get", "/api/inbox"),
        ("get", "/api/inbox/count"),
        ("get", "/api/inbox/1/messages"),
        ("post", "/api/drafts/threads/1"),
        ("get", "/api/prices?brand_id=1"),
        ("post", "/api/send/threads/1/prepare"),
        ("get", "/api/send/settings/1"),
        ("get", "/api/classifications/policy?brand_id=1"),
        ("put", "/api/classifications/supervisors?brand_id=1"),
        ("get", "/api/settings/routing?brand_id=1"),
        ("post", "/api/ai/prompts/preview?brand_id=1"),
    ],
)
def test_removed_reply_endpoints_are_absent(client, classified_data, method, path):
    response = getattr(client, method)(path)
    assert response.status_code == 404


def test_scheduler_tick_keeps_classification_without_reply_jobs(client, settings, monkeypatch):
    from app.services import scheduler

    jobs = []

    class InlineThread:
        def __init__(self, target, args=(), **kwargs):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

        def is_alive(self):
            return False

    worker = scheduler.Scheduler(client.app.state.session_factory, settings)
    monkeypatch.setattr(scheduler.threading, "Thread", InlineThread)
    monkeypatch.setattr(scheduler.audit_retention, "due", lambda *a: False)
    monkeypatch.setattr(worker, "claim", lambda *a: True)
    monkeypatch.setattr(worker, "execute", jobs.append)
    worker.tick()
    worker.tick()
    assert jobs == list(scheduler.INTERVALS) * 2
    assert set(jobs) == {"classify", "notify", "comments", "metrics", "ideation", "publish"}
    assert worker.last_tick > 0


def test_dashboard_trends_boundaries_and_shared_definitions(client, workspace, monkeypatch):
    now = datetime(2026, 10, 4, 12, tzinfo=UTC)  # 台北週日，7 日範圍正好等於本週。
    monkeypatch.setattr(dashboard, "utc_now", lambda: now)
    with client.app.state.session_factory.begin() as session:
        account = session.get(Account, workspace["fb_id"])

        def conversation(name, when, reply=None, historical=False, kind="comment_thread"):
            thread, message = add_thread(session, account, name, when, kind=kind)
            message.is_historical = historical
            if reply is not None:
                session.add_all(
                    [
                        Message(
                            thread_id=thread.id,
                            external_id=f"{name}-out-{i}",
                            direction="out",
                            author_type="brand",
                            text="[測試] 回覆",
                            sent_at=reply + timedelta(seconds=i * 30),
                        )
                        for i in range(2)
                    ]
                )
            return thread, message

        early = datetime(2026, 9, 30, 15, 59, tzinfo=UTC)
        late = datetime(2026, 9, 30, 16, tzinfo=UTC)
        conversation("boundary-before", early, late)
        conversation("boundary-after", late, late)
        conversation("history", late, historical=True)
        conversation("retired-dm", late, late, kind="dm")
        manual, _ = conversation("manual", late)
        manual.status = "replied"  # 人工標記不構成回覆樣本。
        conversation("future", now + timedelta(seconds=1))
        conversation("prior-week", now - timedelta(days=10), late)
        _, duplicate = conversation("idempotent", late)
        session.flush()
        # 平台唯一鍵的重送插入被忽略，摘要與趨勢均只計同一筆。
        from sqlalchemy.dialects.sqlite import insert

        session.execute(
            insert(Message)
            .values(
                thread_id=duplicate.thread_id,
                external_id=duplicate.external_id,
                direction="in",
                author_type="fan",
                text="[測試] 重送",
                sent_at=late,
            )
            .on_conflict_do_nothing(index_elements=["thread_id", "external_id"])
        )

    path = f"/api/dashboard/trends?brand_id={workspace['brand_id']}&days=7"
    response = client.get(path)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["days"] == 7 and value["timezone"] == "Asia/Taipei"
    assert [row["date"] for row in value["series"]] == [
        (date(2026, 9, 28) + timedelta(days=i)).isoformat() for i in range(7)
    ]
    rows = {row["date"]: row for row in value["series"]}
    assert rows["2026-09-30"]["new_messages"] == 1
    assert rows["2026-10-01"]["new_messages"] == 4
    assert rows["2026-09-29"] == {
        "date": "2026-09-29",
        "new_messages": 0,
    }
    assert all(set(row) == {"date", "new_messages"} for row in value["series"])
    summary = client.get(f"/api/dashboard?brand_id={workspace['brand_id']}").json()
    assert sum(row["new_messages"] for row in value["series"]) == summary["new_messages"]
    assert summary["new_comments"] == 5
    assert summary["top_intent"] is None
    assert (
        not {"first_reply_seconds", "first_reply_samples", "pending_threads", "stages"}
        & summary.keys()
    )


@pytest.mark.parametrize("days", [0, 1, 6, 8, 29, 31, -7, "seven", "7.5", ""])
def test_dashboard_trends_reject_days(client, workspace, days):
    assert client.get(f"/api/dashboard/trends?days={days}").status_code == 422


def test_dashboard_trends_permissions_and_empty(client, workspace, monkeypatch):
    now = datetime(2020, 1, 15, tzinfo=UTC)
    monkeypatch.setattr(dashboard, "utc_now", lambda: now)
    for brand_id in (workspace["brand_id"], workspace["other_brand"]):
        with client.app.state.session_factory.begin() as session:
            account = session.scalar(select(Account).where(Account.brand_id == brand_id))
            add_thread(session, account, f"visible-{brand_id}", now)
    result = client.get("/api/dashboard/trends").json()
    assert len(result["series"]) == result["days"] == 30
    assert sum(row["new_messages"] for row in result["series"]) == 2
    for role in ("marketing", "viewer"):
        with client.app.state.session_factory.begin() as session:
            staff = session.get(Staff, workspace["staff_id"])
            staff.role = role
            if not session.scalar(
                select(StaffBrand).where(
                    StaffBrand.staff_id == staff.id, StaffBrand.brand_id == workspace["brand_id"]
                )
            ):
                session.add(StaffBrand(staff_id=staff.id, brand_id=workspace["brand_id"]))
        value = client.get("/api/dashboard/trends?days=7")
        assert value.status_code == 200
        assert sum(row["new_messages"] for row in value.json()["series"]) == 1
        hidden = client.get(f"/api/dashboard/trends?brand_id={workspace['other_brand']}")
        assert hidden.status_code == 404
        assert client.get("/api/dashboard/trends?brand_id=999999").status_code == 404
    with client.app.state.session_factory.begin() as session:
        from sqlalchemy import delete

        session.execute(delete(StaffBrand).where(StaffBrand.staff_id == workspace["staff_id"]))
    empty = client.get("/api/dashboard/trends").json()
    assert len(empty["series"]) == 30
    assert all(row == {"date": row["date"], "new_messages": 0} for row in empty["series"])
    client.cookies.clear()
    assert client.get("/api/dashboard/trends").status_code == 401


def test_dashboard_trends_scale_read_only(client, workspace, monkeypatch, tmp_path):
    import json
    import os
    from time import perf_counter

    from sqlalchemy import event

    from app.services.access import BrandAccess

    now = datetime(2026, 8, 31, 12, tzinfo=UTC)
    monkeypatch.setattr(dashboard, "utc_now", lambda: now)
    with client.app.state.session_factory.begin() as session:
        for i in range(500):
            account = session.get(Account, workspace["fb_id"] if i % 2 else workspace["line_id"])
            start = now - timedelta(days=i % 30, hours=2)
            thread, _ = add_thread(session, account, f"scale-{i}", start)
            session.add_all(
                [
                    Message(
                        thread_id=thread.id,
                        external_id=f"scale-{i}-{j}",
                        direction="in" if j == 1 else "out",
                        author_type="fan" if j == 1 else "brand",
                        text="[測試] 統計",
                        sent_at=start + timedelta(minutes=j * 10),
                    )
                    for j in range(1, 4)
                ]
            )
    sql = []
    engine = client.app.state.session_factory.kw["bind"]

    def record(connection, cursor, statement, parameters, context, many):
        sql.append(statement)

    def best_of(action, runs=5):
        # 首次呼叫含 SQL 編譯、延遲匯入與頁面快取等一次性成本，verify_all 平行跑瀏覽器檢查時
        # 會被 CPU 競爭放大到 0.8 秒以上；門檻只量暖機後多次中的最佳值。N+1 查詢、逐列重算
        # 等規模退化每一次都會發生，最佳值仍會超標；偶發排程延遲則只影響部分次數。
        timings = []
        for _ in range(runs):
            started = perf_counter()
            action()
            timings.append(perf_counter() - started)
        return min(timings)

    def api_trends():
        assert client.get("/api/dashboard/trends").status_code == 200

    event.listen(engine, "before_cursor_execute", record)
    try:
        with client.app.state.session_factory() as session:
            access = BrandAccess(session, session.get(Staff, workspace["staff_id"]))
            sql.clear()
            started = perf_counter()
            value = dashboard.trends(access, days=30, now=now)
            cold = perf_counter() - started
            assert sum(row["new_messages"] for row in value["series"]) == 1000
            assert all(set(row) == {"date", "new_messages"} for row in value["series"])
            selects = [s for s in sql if s.lstrip().upper().startswith("SELECT")]
            assert len(selects) == 1
            assert all(s in selects or s == "BEGIN" for s in sql)
            elapsed = best_of(lambda: dashboard.trends(access, days=30, now=now))
        sql.clear()
        started = perf_counter()
        api_trends()
        api_cold = perf_counter() - started
        api_elapsed = best_of(api_trends)
        assert not any(
            "BEGIN IMMEDIATE" in s.upper()
            or s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
            for s in sql
        )
    finally:
        event.remove(engine, "before_cursor_execute", record)
    limit = 1 if os.environ.get("CI") else 0.3
    (tmp_path / "trend-performance.json").write_text(
        json.dumps(
            {
                "messages": 2000,
                "threads": 500,
                "service_ms": elapsed * 1000,
                "api_ms": api_elapsed * 1000,
                "cold_service_ms": cold * 1000,
                "cold_api_ms": api_cold * 1000,
                "limit_ms": limit * 1000,
            }
        ),
        encoding="utf-8",
    )
    assert elapsed < limit and api_elapsed < limit


def add_thread(session, account, name, when, *, kind="comment_thread", status="pending"):
    contact = Contact(
        brand_id=account.brand_id, platform=account.platform, external_id=name, display_name=name
    )
    session.add(contact)
    session.flush()
    thread = Thread(
        brand_id=account.brand_id,
        account_id=account.id,
        external_id=name,
        kind=kind,
        contact_id=contact.id,
        last_inbound_at=when,
        status=status,
    )
    session.add(thread)
    session.flush()
    message = Message(
        thread_id=thread.id,
        external_id=name,
        direction="in",
        author_type="fan",
        text="[測試] 服務需求類型",
        sent_at=when,
    )
    session.add(message)
    session.flush()
    return thread, message


@pytest.fixture
def workspace(client, classified_data):
    now = utc_now()
    with client.app.state.session_factory.begin() as session:
        other = Brand(slug="workspace-other", name="[測試] 另一品牌")
        session.add(other)
        session.flush()
        line = Account(
            brand_id=classified_data["brand_id"],
            platform="line",
            external_id="e-line",
            name="[測試] LINE",
        )
        fb = Account(
            brand_id=line.brand_id, platform="facebook", external_id="e-fb", name="[測試] FB"
        )
        hidden = Account(
            brand_id=other.id, platform="line", external_id="e-hidden", name="[測試] 跨品牌"
        )
        session.add_all([line, fb, hidden])
        session.flush()
        first, message = add_thread(session, line, "e-first", now - timedelta(hours=3))
        second, _ = add_thread(session, fb, "e-second", now - timedelta(hours=21))
        third, _ = add_thread(session, hidden, "e-third", now)
        return {
            **classified_data,
            "thread_id": first.id,
            "message_id": message.id,
            "second_id": second.id,
            "other_thread": third.id,
            "other_brand": other.id,
            "line_id": line.id,
            "fb_id": fb.id,
        }


def body(thread, **values):
    return {
        "version": thread["version"],
        "stage": thread["stage"],
        "owner_staff_id": thread["owner_staff_id"],
        "list_color": thread["list_color"],
        "booking_date": thread["booking_date"],
        "booking_units": thread["booking_units"],
        **values,
    }


def inbox(client, **query):
    result = client.get("/api/inbox", params=query)
    assert result.status_code == 200, result.text
    return result.json()["items"]


def test_dashboard_taipei_week_nulls_and_first_actual_reply(client, workspace, monkeypatch):
    now = datetime(2026, 9, 27, 16, 30, tzinfo=UTC)  # 台北週一 00:30
    start = now.replace(minute=0)
    monkeypatch.setattr(dashboard, "utc_now", lambda: now)
    with client.app.state.session_factory.begin() as session:
        account = session.get(Account, workspace["line_id"])
        before, _ = add_thread(session, account, "previous-week", start - timedelta(seconds=1))
        first, _ = add_thread(session, account, "this-week-reply", start)
        second, _ = add_thread(
            session, account, "this-week-manual", start + timedelta(minutes=5), status="replied"
        )
        second.stage = "booked"
        session.add_all(
            [
                Message(
                    thread_id=first.id,
                    external_id="reply1",
                    direction="out",
                    author_type="brand",
                    text="收到",
                    sent_at=start + timedelta(minutes=10),
                ),
                Message(
                    thread_id=first.id,
                    external_id="reply2",
                    direction="out",
                    author_type="brand",
                    text="再回覆",
                    sent_at=start + timedelta(minutes=20),
                ),
                Message(
                    thread_id=before.id,
                    external_id="reply-previous",
                    direction="out",
                    author_type="brand",
                    text="收到",
                    sent_at=start + timedelta(minutes=1),
                ),
            ]
        )
    data = client.get(f"/api/dashboard?brand_id={workspace['brand_id']}")
    assert data.status_code == 200, data.text
    data = data.json()
    assert datetime.fromisoformat(data["week_start"]) == start
    assert data["new_messages"] == 2
    assert data["new_comments"] == 2 and data["top_intent"] is None
    assert data["intents"] == [{"intent": "unclassified", "count": 2}]
    assert not data["highest_reach"]
    other = client.get(f"/api/dashboard?brand_id={workspace['other_brand']}").json()
    assert other["new_messages"] == 0 and other["top_intent"] is None


def test_dashboard_uses_latest_snapshot_excludes_unknown(client, workspace, monkeypatch):
    now = datetime(2026, 9, 26, 12, tzinfo=UTC)
    monkeypatch.setattr(dashboard, "utc_now", lambda: now)
    with client.app.state.session_factory.begin() as session:
        for name, reach in [
            ("normal", 100),
            ("zero", 0),
            ("unknown", None),
        ]:
            post = Post(
                account_id=workspace["fb_id"],
                external_id=name,
                caption=name,
                media_type="image",
                published_at=now - timedelta(days=1),
            )
            session.add(post)
            session.flush()
            for step, value in enumerate([5000, reach]):
                session.add(
                    MetricSnapshot(
                        post_id=post.id,
                        captured_at=now - timedelta(minutes=2 - step),
                        reach=value,
                    )
                )
    data = client.get(f"/api/dashboard?brand_id={workspace['brand_id']}").json()
    assert [p["reach"] for p in data["highest_reach"]] == [100, 0]
    assert [p["reach"] for p in data["lowest_reach"]] == [0, 100]


def test_marketing_kpis_comments_and_current_classifications(client, workspace, monkeypatch):
    from app.models import Classification
    from app.services import classify

    now = datetime(2026, 9, 30, 12, tzinfo=UTC)
    start = datetime(2026, 9, 27, 16, tzinfo=UTC)
    monkeypatch.setattr(dashboard, "utc_now", lambda: now)
    with client.app.state.session_factory.begin() as session:
        account = session.get(Account, workspace["fb_id"])

        def classified(name, intent, *, stale=False, kind="comment_thread", when=start):
            _, message = add_thread(session, account, name, when, kind=kind)
            context, _ = classify.context_for(session, message)
            row = Classification(
                message_id=message.id,
                engine="keyword",
                intent=intent,
                sentiment="neutral",
                action="classified",
                sensitive=False,
                confidence=1,
                input_hash=classify.fingerprint(message.text, context),
            )
            session.add(row)
            if stale:
                message.text = "[測試] 修改過的訊息"
            return message

        classified("week-start", "booking")
        classified("public", "booking", kind="comment_thread")
        classified("previous-week", "price", when=start - timedelta(seconds=1))
        classified("future", "price", when=now + timedelta(seconds=1))
        classified("stale", "price", stale=True)
        for i in range(3):
            classified(f"spam-{i}", "spam")
        replaced = classified("reclassified", "price")
        session.flush()
        context, _ = classify.context_for(session, replaced)
        session.add(
            Classification(
                message_id=replaced.id,
                engine="keyword",
                intent="booking",
                sentiment="neutral",
                action="classified",
                sensitive=False,
                confidence=1,
                input_hash=classify.fingerprint(replaced.text, context),
            )
        )
        brand = classified("brand-comment", "price", kind="comment_thread")
        brand.author_type = "brand"
        outgoing = classified("outgoing-comment", "price", kind="comment_thread")
        outgoing.direction = "out"
        classified("unclassified-code", "unknown")
    value = client.get(f"/api/dashboard?brand_id={workspace['brand_id']}").json()
    assert value["new_comments"] == 8
    assert value["top_intent"] == {"intent": "booking", "count": 3}
    assert (
        client.get(f"/api/dashboard?brand_id={workspace['other_brand']}").json()["top_intent"]
        is None
    )


def test_brand_and_export_settings_version_and_write_check(client, workspace, tmp_path):
    path = f"/api/settings/brand?brand_id={workspace['brand_id']}"
    assert client.get(path).status_code == 404
    assert (
        client.put(path, json={"version": 1, "start": "09:30", "end": "18:30"}).status_code == 404
    )
    initial = client.get("/api/settings/export").json()
    target = tmp_path / "export-test"
    value = {"version": initial["version"], "export_root": str(target)}
    assert (
        client.put("/api/settings/export", json={**value, "export_root": "relative"}).status_code
        == 422
    )
    result = client.put("/api/settings/export", json=value)
    assert result.status_code == 200, result.text
    assert result.json()["writable"] and result.json()["engine_available"]
    assert target.is_dir() and not list(target.iterdir())
    assert client.put("/api/settings/export", json=value).status_code == 409
    file = target / "keep.txt"
    file.write_text("preserve")
    result = client.put(
        "/api/settings/export", json={"version": result.json()["version"], "export_root": str(file)}
    )
    assert result.status_code == 422 and file.read_text() == "preserve"


def generate(client, data):
    result = client.post(
        f"/api/drafts/threads/{data['thread_id']}", json={"provider": "gemini_api"}
    )
    assert result.status_code == 200, result.text
    return result.json()
