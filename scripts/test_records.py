"""Synthetic records used only by isolated tests and acceptance scripts."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    Account,
    AuditLog,
    Brand,
    Contact,
    Message,
    MetricSnapshot,
    Post,
    Setting,
    Staff,
    StaffBrand,
    Thread,
)
from app.services.passwords import initialize_password

QUESTIONS = (
    "標準方案怎麼計價？",
    "預約需要提前幾天？",
    "可以先說明我的需求嗎？",
    "客製需求是否需要先評估？",
    "使用流程有哪些步驟？",
    "可以安排諮詢嗎？",
    "上次服務有個問題想反映。",
    "想洽談合作，請問聯絡方式？",
    "可以詢問可預約日期嗎？",
    "有新手入門說明嗎？",
)


def seed_records(session: Session, settings: Settings, *, include_content=True) -> dict[str, int]:
    database = Path(session.get_bind().url.database).resolve()
    if database != Path(settings.database_path).resolve() or not any(
        part == ".runtime" or part.startswith("pytest-") or part.startswith("test_")
        for part in database.parts
    ):
        raise ValueError("Fixtures require an isolated test database")
    added = 0

    def ensure(model, lookup: dict, **values):
        nonlocal added
        existing = session.scalar(select(model).filter_by(**lookup))
        if existing is not None:
            return existing, False
        item = model(**lookup, **values)
        session.add(item)
        session.flush()
        added += 1
        return item, True

    brand, _ = ensure(
        Brand,
        {"slug": "TEST"},
        name="測試品牌",
    )
    from app.models import PromptVersion
    from app.services.prompts import current, scope

    if current(session, brand.id) is None:
        session.add(
            PromptVersion(
                scope=scope(brand.id),
                task="draft",
                brand_id=brand.id,
                revision=1,
                content="依已提供的品牌資訊回答；未知事項先澄清，報價只引用核定價目表。",
                actor="system:seed",
            )
        )
    staff = {}
    for username, role, display_name in (
        ("admin", "admin", "測試管理員"),
        ("marketing_test", "marketing", "行銷測試帳號"),
        ("viewer_test", "viewer", "唯讀測試帳號"),
    ):
        person, created = ensure(
            Staff, {"username": username}, role=role, display_name=display_name, password_hash=None
        )
        staff[username] = person
        initialize_password(session, person, getattr(settings, f"{username}_initial_password"))
        # 重跑不得恢復管理員已撤銷的品牌權限。
        if created and username == "marketing_test":
            ensure(StaffBrand, {"staff_id": person.id, "brand_id": brand.id})

    if include_content:
        accounts = {}
        for platform in ("line", "facebook", "instagram"):
            accounts[platform], _ = ensure(
                Account,
                {
                    "brand_id": brand.id,
                    "platform": platform,
                    "external_id": f"test:test:{platform}",
                },
                name=f"[測試] TEST {platform}",
                status="disconnected",
            )

        posts = {"facebook": [], "instagram": []}
        published = datetime(2026, 9, 20, 1, 0, tzinfo=UTC)
        for index in range(10):
            platform = "facebook" if index % 2 == 0 else "instagram"
            post, _ = ensure(
                Post,
                {"account_id": accounts[platform].id, "external_id": f"test:post:{index + 1}"},
                caption=f"[隔離測試] {QUESTIONS[index]}",
                permalink=None,
                media_type="video",
                published_at=published + timedelta(hours=index),
                schedule_tier="daily",
            )
            posts[platform].append(post)
            for step, hours in enumerate((1, 6, 24), start=1):
                ensure(
                    MetricSnapshot,
                    {"post_id": post.id, "captured_at": post.published_at + timedelta(hours=hours)},
                    views=(index + 1) * step * 100,
                    reach=(index + 1) * step * 80,
                    likes=step * 5,
                    comments=step * 2,
                    shares=step,
                    saves=step * 2,
                    extra_json={"fixture": True, "notice": "測試數值，非平台真實成效"},
                )

        message_start = datetime(2026, 9, 24, 2, 0, tzinfo=UTC)
        for index in range(40):
            platform = ("facebook", "instagram")[index % 2]
            contact, _ = ensure(
                Contact,
                {
                    "platform": platform,
                    "brand_id": brand.id,
                    "external_id": f"test:fan:{index + 1}",
                },
                display_name=f"測試用戶 {index + 1:02d}",
                profile_json={"fixture": True},
            )
            is_comment = True
            post = posts[platform][index % 5] if is_comment else None
            sent_at = message_start + timedelta(minutes=index * 10)
            thread, _ = ensure(
                Thread,
                {
                    "account_id": accounts[platform].id,
                    "kind": "comment_thread" if is_comment else "dm",
                    "external_id": f"test:thread:{index + 1}",
                },
                brand_id=brand.id,
                contact_id=contact.id,
                post_id=post.id if post else None,
                owner_staff_id=staff["marketing_test"].id if is_comment else None,
                source_ref_json={"fixture": True, "source": "isolated-fixture"},
                last_inbound_at=sent_at,
            )
            ensure(
                Message,
                {"thread_id": thread.id, "external_id": f"test:message:{index + 1}"},
                direction="in",
                author_type="fan",
                text=f"[隔離測試] {QUESTIONS[index % 10]}",
                sent_at=sent_at,
            )

    for key, value in {
        "export_root": str(settings.export_root),
        "classification_threshold": 0.8,
        "auto_reply_emergency_stop": True,
    }.items():
        ensure(Setting, {"key": key}, value_json=value)

    if added:
        session.add(
            AuditLog(
                actor="system:seed_records",
                action="test.seed",
                target_type="brand",
                target_id=brand.id,
                brand_id=brand.id,
                detail_json={"inserted_rows": added, "fixture": True},
            )
        )
        session.flush()

    return {
        model.__tablename__: session.scalar(select(func.count()).select_from(model))
        for model in (Brand, Staff, Account, Post, MetricSnapshot, Contact, Thread, Message)
    }
