from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UTCDateTime, Versioned, utc_now

PLATFORMS = ("line", "facebook", "instagram", "youtube", "tiktok", "threads")


def choices(name: str, *values: str) -> Enum:
    return Enum(
        *values, name=name, native_enum=False, create_constraint=True, validate_strings=True
    )


class Brand(Versioned, Base):
    __tablename__ = "brands"

    slug: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    business_hours: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=lambda: {"timezone": "Asia/Taipei", "start": "09:00", "end": "18:00"}
    )
    auto_reply_level: Mapped[str] = mapped_column(
        choices("reply_level", "L0", "L1", "L2"), default="L0"
    )
    auto_reply_enabled: Mapped[bool] = mapped_column(default=False)
    marketing_dm_enabled: Mapped[bool] = mapped_column(default=False, server_default="0")


class Staff(Versioned, Base):
    __tablename__ = "staff"

    username: Mapped[str] = mapped_column(String(80), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    # 未設定密碼即無法登入；seed 不替使用者產生或猜測憑證。
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(choices("staff_role", "admin", "marketing", "viewer"))
    active: Mapped[bool] = mapped_column(default=True)
    must_change_password: Mapped[bool] = mapped_column(default=False, server_default="0")
    # 管理員自助復原用的一次性復原碼，只存雜湊；使用或重新產生後舊碼即失效。
    recovery_code_hash: Mapped[str | None] = mapped_column(String(255))
    recovery_code_created_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # 介面語言偏好；空值表示沿用瀏覽器記住的語言（預設繁體中文）。
    language: Mapped[str | None] = mapped_column(String(10))


class StaffBrand(Base):
    __tablename__ = "staff_brands"
    __table_args__ = (UniqueConstraint("staff_id", "brand_id"),)

    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id"))
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)


class BrandPerson(Versioned, Base):
    __tablename__ = "brand_people"
    __table_args__ = (UniqueConstraint("id", "brand_id"),)

    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(
        choices("brand_person_role", "owner", "customer_service", "other")
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(default=True)


class Account(Versioned, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("brand_id", "platform", "external_id"),
        UniqueConstraint("id", "brand_id"),
    )

    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    platform: Mapped[str] = mapped_column(choices("account_platform", *PLATFORMS))
    external_id: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(200))
    # 只放 .env 變數名稱；如需加密儲存 token，另經憑證服務處理。
    send_enabled: Mapped[bool] = mapped_column(default=False, server_default="0")
    token_ref: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(
        choices("account_status", "disconnected", "connected", "error"),
        default="disconnected",
    )


class Contact(Versioned, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("platform", "brand_id", "external_id"),
        UniqueConstraint("id", "brand_id"),
    )

    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    platform: Mapped[str] = mapped_column(choices("contact_platform", *PLATFORMS))
    external_id: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(200))
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Post(Versioned, Base):
    __tablename__ = "posts"
    __table_args__ = (
        UniqueConstraint("account_id", "external_id"),
        UniqueConstraint("id", "account_id"),
    )

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(255))
    permalink: Mapped[str | None] = mapped_column(Text)
    caption: Mapped[str] = mapped_column(Text, default="")
    media_type: Mapped[str] = mapped_column(String(40))
    visibility: Mapped[str | None] = mapped_column(String(20))
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    published_at: Mapped[datetime] = mapped_column(UTCDateTime())
    schedule_tier: Mapped[str] = mapped_column(
        choices("schedule_tier", "hourly", "daily", "weekly"), default="hourly"
    )
    thumbnail: Mapped["PostThumbnail | None"] = relationship(  # noqa: F821
        uselist=False, viewonly=True
    )

    @property
    def thumbnail_url(self) -> str | None:
        # 摘要做快取破壞；圖片本身只經登入後的 API 讀取，不暴露平台 CDN 網址。
        image = self.thumbnail
        if image is None or image.status != "ready" or not image.digest:
            return None
        return f"/api/posts/{self.id}/thumbnail?v={image.digest[:12]}"


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"
    __table_args__ = (
        UniqueConstraint("post_id", "captured_at"),
        Index("uq_metric_post_sync_slot", "post_id", "sync_slot", unique=True),
        CheckConstraint("completion_rate BETWEEN 0 AND 1", name="completion_rate_range"),
    )

    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), index=True)
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime())
    sync_slot: Mapped[datetime | None] = mapped_column(UTCDateTime())
    views: Mapped[int | None]
    reach: Mapped[int | None]
    likes: Mapped[int | None]
    comments: Mapped[int | None]
    shares: Mapped[int | None]
    saves: Mapped[int | None]
    avg_watch_time: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    completion_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    extra_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Thread(Versioned, Base):
    __tablename__ = "threads"
    __table_args__ = (
        UniqueConstraint("account_id", "kind", "external_id"),
        UniqueConstraint("id", "brand_id"),
        ForeignKeyConstraint(["account_id", "brand_id"], ["accounts.id", "accounts.brand_id"]),
        ForeignKeyConstraint(["contact_id", "brand_id"], ["contacts.id", "contacts.brand_id"]),
        ForeignKeyConstraint(["post_id", "account_id"], ["posts.id", "posts.account_id"]),
        CheckConstraint("booking_units > 0", name="positive_booking_units"),
        ForeignKeyConstraint(
            ["owner_person_id", "brand_id"], ["brand_people.id", "brand_people.brand_id"]
        ),
        CheckConstraint(
            "owner_staff_id IS NULL OR owner_person_id IS NULL", name="single_assignee"
        ),
        Index("ix_threads_brand_status", "brand_id", "status"),
    )

    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"))
    account_id: Mapped[int]
    external_id: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(choices("thread_kind", "comment_thread", "dm"))
    contact_id: Mapped[int | None]
    post_id: Mapped[int | None]
    source_ref_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    owner_staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"))
    owner_person_id: Mapped[int | None]
    assignment_mode: Mapped[str] = mapped_column(
        choices("assignment_mode", "auto", "manual"), default="auto"
    )
    status: Mapped[str] = mapped_column(
        choices("thread_status", "pending", "in_progress", "replied", "closed"), default="pending"
    )
    stage: Mapped[str] = mapped_column(
        choices("thread_stage", "inquiry", "quoted", "booked", "completed", "follow_up"),
        default="inquiry",
    )
    list_color: Mapped[str | None] = mapped_column(choices("list_color", "red", "green", "black"))
    booking_date: Mapped[date | None]
    booking_units: Mapped[int | None]
    last_inbound_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_outbound_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Message(Versioned, Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("thread_id", "external_id"),
        Index("ix_messages_thread_sent", "thread_id", "sent_at"),
    )

    thread_id: Mapped[int] = mapped_column(ForeignKey("threads.id"))
    # 同一留言串可以有多位粉絲，不能只靠 thread.contact_id 表示每則訊息的對象。
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))
    external_id: Mapped[str] = mapped_column(String(255))
    direction: Mapped[str] = mapped_column(choices("message_direction", "in", "out"))
    sent_by_staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"))
    sender_name: Mapped[str | None] = mapped_column(String(200))
    comment_parent_id: Mapped[str | None] = mapped_column(String(255))
    comment_root_id: Mapped[str | None] = mapped_column(String(255))
    comment_parent_known: Mapped[bool] = mapped_column(default=False)
    author_type: Mapped[str] = mapped_column(choices("author_type", "fan", "brand", "ai", "system"))
    text: Mapped[str] = mapped_column(Text)
    attachments_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime())
    edited_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    content_observed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    is_historical: Mapped[bool] = mapped_column(default=False)
    is_redelivery: Mapped[bool] = mapped_column(default=False)
    sources_json: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["webhook"])


class RawEvent(Base):
    __tablename__ = "raw_events"
    __table_args__ = (UniqueConstraint("platform", "account_external_id", "external_id"),)

    platform: Mapped[str | None] = mapped_column(choices("event_platform", *PLATFORMS))
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"), index=True)
    account_external_id: Mapped[str | None] = mapped_column(String(255))
    external_id: Mapped[str | None] = mapped_column(String(255))
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    signature_ok: Mapped[bool]
    source: Mapped[str] = mapped_column(String(16), default="webhook")
    payload_json: Mapped[Any] = mapped_column(JSON)
    processed: Mapped[bool] = mapped_column(default=False)
    error: Mapped[str | None] = mapped_column(Text)


class InboundJob(Base):
    __tablename__ = "inbound_jobs"
    __table_args__ = (UniqueConstraint("message_id", "task"),)

    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), index=True)
    task: Mapped[str] = mapped_column(choices("inbound_task", "classify", "notify"))
    status: Mapped[str] = mapped_column(
        choices("inbound_job_status", "pending", "processing", "completed", "failed"),
        default="pending",
        index=True,
    )
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)
    lease_id: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime())


class Classification(Base):
    __tablename__ = "classifications"
    __table_args__ = (CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),)

    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), index=True)
    engine: Mapped[str] = mapped_column(
        choices("classification_engine", "jev", "keyword", "policy")
    )
    intent: Mapped[str] = mapped_column(String(40))
    sentiment: Mapped[str] = mapped_column(String(40))
    sensitive: Mapped[bool]
    action: Mapped[str] = mapped_column(String(40))
    confidence: Mapped[float]
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    input_hash: Mapped[str | None] = mapped_column(String(64))
    urgency: Mapped[float | None]
    sentiment_score: Mapped[float | None]
    policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reasons_json: Mapped[list[str]] = mapped_column(JSON, default=list)


class Draft(Versioned, Base):
    __tablename__ = "drafts"

    thread_id: Mapped[int] = mapped_column(ForeignKey("threads.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    original_text: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(120))
    price_item_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(
        choices("draft_status", "draft", "approved", "sent", "discarded"), default="draft"
    )
    created_by: Mapped[int | None] = mapped_column(ForeignKey("staff.id"))
    needs_edit: Mapped[bool] = mapped_column(default=True)
    review_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_hash: Mapped[str | None] = mapped_column(String(64))
    price_snapshot_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class PriceItem(Versioned, Base):
    __tablename__ = "price_items"
    __table_args__ = (CheckConstraint("price >= 0", name="nonnegative_price"),)

    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    category: Mapped[str] = mapped_column(String(100))
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    unit: Mapped[str] = mapped_column(String(80))
    conditions: Mapped[str] = mapped_column(Text, default="")
    needs_human: Mapped[bool] = mapped_column(default=True)
    effective_from: Mapped[date | None]
    approved_by: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(default=False)

    archived: Mapped[bool] = mapped_column(default=False)


class PriceItemHistory(Base):
    __tablename__ = "price_item_history"

    price_item_id: Mapped[int] = mapped_column(ForeignKey("price_items.id"), index=True)
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("staff.id"))
    changed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    before_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    after_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class AdMetricDaily(Base):
    __tablename__ = "ad_metrics_daily"
    __table_args__ = (UniqueConstraint("account_id", "date", "campaign_id"),)

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    date: Mapped[date]
    campaign_id: Mapped[str] = mapped_column(String(255))
    spend: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    impressions: Mapped[int | None]
    clicks: Mapped[int | None]
    conversations_started: Mapped[int | None]
    cost_per_conversation: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))


class AIRun(Base):
    __tablename__ = "ai_runs"

    task: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(120))
    mode: Mapped[str] = mapped_column(choices("ai_mode", "api", "subscription"))
    trigger: Mapped[str] = mapped_column(choices("ai_trigger", "manual", "background"))
    tokens_in: Mapped[int | None]
    tokens_out: Mapped[int | None]
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 8))
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"), index=True)
    ok: Mapped[bool]
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None]


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        ForeignKeyConstraint(["thread_id", "brand_id"], ["threads.id", "threads.brand_id"]),
        Index("ix_notifications_status_due", "status", "due_at"),
    )

    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"))
    thread_id: Mapped[int]
    kind: Mapped[str] = mapped_column(choices("notification_kind", "new", "reminder", "urgent"))
    due_at: Mapped[datetime] = mapped_column(UTCDateTime())
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(
        choices("notification_status", "pending", "sent", "failed", "cancelled"), default="pending"
    )
    event_key: Mapped[str | None] = mapped_column(String(160), unique=True)
    message_id: Mapped[int | None] = mapped_column(ForeignKey("messages.id"))
    reason: Mapped[str | None] = mapped_column(String(40))
    delivery_id: Mapped[int | None] = mapped_column(ForeignKey("notification_deliveries.id"))


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"

    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    retry_key: Mapped[str] = mapped_column(String(36), unique=True)
    recipient: Mapped[str] = mapped_column(String(64))
    messages_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    lease_id: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    first_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime())
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error: Mapped[str | None] = mapped_column(String(80))


class Setting(Versioned, Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(120), unique=True)
    value_json: Mapped[Any] = mapped_column(JSON)


class AuditLog(Base):
    __tablename__ = "audit_log"
    # 例行紀錄依類型與時間清理；也讓依類型查詢不用掃描整張表。
    __table_args__ = (Index("ix_audit_log_action_at", "action", "at"),)

    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id"), index=True)
    actor: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(120))
    target_type: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[int | None]
    detail_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
