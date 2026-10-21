import base64
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import or_, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from app.config import Settings
from app.logging_config import log_failure
from app.models import (
    Account,
    AuditLog,
    Contact,
    InboundJob,
    Message,
    MetaApiCall,
    Post,
    RawEvent,
    Thread,
)
from app.models.base import utc_now
from app.models.domain import PLATFORMS
from app.schemas.ingest import EventInput, IngestResult, MessageInput
from app.services import comment_threads, data_retention


@dataclass(frozen=True)
class Outcome:
    status: int
    result: IngestResult


class InvalidEvent(Exception):
    def __init__(self, code: str, status: int = 422):
        self.code = code
        self.status = status
        super().__init__(code)


def require_key(settings: Settings, supplied: str | None) -> None:
    expected = settings.ingest_api_key
    if (
        expected is None
        or not supplied
        or not hmac.compare_digest(
            expected.get_secret_value().encode("utf-8"), supplied.encode("utf-8")
        )
    ):
        raise HTTPException(401, "Ingest API 金鑰無效")


def _invalid_constant(_value):
    raise ValueError("非標準 JSON 常數")


def _external_id(value: Any) -> str | None:
    if isinstance(value, str) and 0 < len(value) <= 255 and not any(c.isspace() for c in value):
        return value
    return None


def strip_credentials(value):
    if isinstance(value, dict):
        return {
            k: (
                "[REDACTED]"
                if "token" in k.lower() or "secret" in k.lower()
                else strip_credentials(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [strip_credentials(v) for v in value]
    return value


def _save_raw(session: Session, body: bytes, source: str) -> tuple[RawEvent, Any]:
    try:
        parsed = json.loads(body, parse_constant=_invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        parsed = None
        payload = {"invalid_json_base64": base64.b64encode(body).decode("ascii")}
    else:
        payload = parsed.get("payload", parsed) if isinstance(parsed, dict) else parsed
    envelope = parsed if isinstance(parsed, dict) else {}
    platform = envelope.get("platform")
    values = {
        "platform": platform if isinstance(platform, str) and platform in PLATFORMS else None,
        "account_external_id": _external_id(envelope.get("account_external_id")),
        "external_id": _external_id(envelope.get("external_id")),
        "signature_ok": envelope.get("signature_ok") is True,
        "source": source,
        "payload_json": strip_credentials(payload),
        "received_at": utc_now(),
        "brand_id": None,
        "processed": False,
        "error": None,
        "updated_at": utc_now(),
    }
    # 第一個 SQL 是寫入：SQLite 先取得寫鎖，並行重送不會在讀後升級鎖時衝突。
    statement = insert(RawEvent).values(**values)
    column = RawEvent.__table__.c.error
    statement = statement.on_conflict_do_update(
        index_elements=["platform", "account_external_id", "external_id"],
        set_=values,
        # 原文已依資料保留規則清除的事件不覆寫，保留它作為冪等紀錄。
        where=or_(column.is_(None), column != data_retention.REMOVED_EVENT),
    ).returning(RawEvent)
    raw = session.scalars(statement).one_or_none()
    if raw is None:
        raw = session.scalars(
            select(RawEvent).where(
                RawEvent.platform == values["platform"],
                RawEvent.account_external_id == values["account_external_id"],
                RawEvent.external_id == values["external_id"],
            )
        ).one()
    return raw, parsed


def _account(session: Session, raw: RawEvent) -> Account:
    accounts = list(
        session.scalars(
            select(Account)
            .where(Account.platform == raw.platform, Account.external_id == raw.account_external_id)
            .limit(2)
        )
    )
    if not accounts:
        raise InvalidEvent("account_not_registered")
    if len(accounts) != 1:
        raise InvalidEvent("account_ambiguous")
    account = accounts[0]

    return account


def _contact(session: Session, account: Account, message: MessageInput) -> Contact:
    source = message.contact
    contact = session.scalar(
        select(Contact).where(
            Contact.platform == account.platform,
            Contact.brand_id == account.brand_id,
            Contact.external_id == source.external_id,
        )
    )
    if contact is None:
        contact = Contact(
            platform=account.platform,
            brand_id=account.brand_id,
            external_id=source.external_id,
            display_name=source.display_name or "未提供名稱",
            profile_json=source.profile_json or {},
        )
        session.add(contact)
        session.flush()

    else:
        if source.display_name is not None:
            contact.display_name = source.display_name
        if source.profile_json is not None:
            contact.profile_json = source.profile_json
    return contact


def _thread(
    session: Session,
    account: Account,
    contact: Contact,
    message: MessageInput,
) -> Thread:
    thread = session.scalar(
        select(Thread).where(
            Thread.account_id == account.id,
            Thread.kind == message.kind,
            Thread.external_id == message.thread_external_id,
        )
    )
    post = None
    if message.post_external_id is not None:
        post = session.scalar(
            select(Post).where(
                Post.account_id == account.id, Post.external_id == message.post_external_id
            )
        )

    if thread is None:
        thread = Thread(
            account_id=account.id,
            brand_id=account.brand_id,
            contact_id=contact.id,
            kind=message.kind,
            external_id=message.thread_external_id,
            post_id=post.id if post else None,
        )
        session.add(thread)
        session.flush()

    if thread.contact_id is None:
        thread.contact_id = contact.id
    if post is not None:
        if thread.post_id not in (None, post.id):
            raise InvalidEvent("conversation_post_conflict")
        thread.post_id = post.id
    # 尚未同步的貼文只保留平台 ID，T1-06 取得真實貼文後再連結，不造假貼文。
    if message.post_external_id is not None:
        previous = thread.source_ref_json.get("post_external_id")
        if previous not in (None, message.post_external_id):
            raise InvalidEvent("conversation_post_conflict")
    references = dict(thread.source_ref_json)
    if message.post_external_id is not None:
        references["post_external_id"] = message.post_external_id
    if references != thread.source_ref_json:
        thread.source_ref_json = references
    return thread


def _advance_thread(thread: Thread, message: MessageInput) -> None:
    field = "last_inbound_at" if message.direction == "in" else "last_outbound_at"
    previous = getattr(thread, field)
    if previous is not None and message.sent_at < previous:
        return
    setattr(thread, field, message.sent_at)
    if message.direction == "in":
        if thread.last_outbound_at is None or message.sent_at > thread.last_outbound_at:
            if thread.status in {"replied", "closed"}:
                thread.status = "pending"
    elif thread.last_inbound_at is None or message.sent_at >= thread.last_inbound_at:
        thread.status = "replied"


def _message(
    session: Session,
    contact: Contact,
    thread: Thread,
    source: MessageInput,
    received_at: datetime,
    origin: str,
    observed_at: datetime,
) -> tuple[str, int]:
    query = select(Message).where(Message.external_id == source.external_id)
    if source.kind == "comment_thread":
        query = query.join(Thread).where(
            Thread.account_id == thread.account_id, Thread.kind == "comment_thread"
        )
    else:
        query = query.where(Message.thread_id == thread.id)
    matches = list(session.scalars(query.limit(2)))
    if len(matches) > 1:
        raise InvalidEvent("comment_identity_ambiguous")
    message = matches[0] if matches else None
    relationship = (
        comment_threads.relation(source.source_ref_json, source.post_external_id)
        if source.kind == "comment_thread"
        else None
    )
    if message is None:
        message = Message(
            thread_id=thread.id,
            contact_id=contact.id,
            external_id=source.external_id,
            direction=source.direction,
            author_type=source.author_type,
            text=source.text,
            attachments_json=source.attachments_json,
            sent_at=source.sent_at,
            edited_at=source.edited_at,
            sources_json=[origin],
            is_historical=origin in {"history", "csv"},
            is_redelivery=source.is_redelivery,
            content_observed_at=observed_at,
            comment_parent_known=relationship is not None,
            comment_parent_id=relationship[0] if relationship else None,
            comment_root_id=(
                relationship[1] or (source.external_id if relationship[0] is None else None)
            )
            if relationship
            else None,
        )
        session.add(message)
        session.flush()
        # Historical imports advance timestamps without reopening manually handled threads.
        previous_status = thread.status
        _advance_thread(thread, source)
        if origin == "history":
            thread.status = previous_status
        if source.direction == "in":
            tasks = (
                ("classify", "notify")
                if origin != "history"
                else ("classify",)
                if source.sent_at >= received_at - timedelta(days=7)
                else ()
            )
            if source.is_redelivery and source.sent_at < received_at - timedelta(hours=24):
                tasks = ()
            if origin == "csv":
                tasks = ()
            session.add_all([InboundJob(message_id=message.id, task=task) for task in tasks])
            return "created_messages", len(tasks)
        return "created_messages", 0

    if source.kind == "comment_thread":
        existing_thread = session.get(Thread, message.thread_id)
        if existing_thread.source_ref_json.get("post_external_id") not in (
            None,
            source.post_external_id,
        ):
            raise InvalidEvent("conversation_post_conflict")
    if message.sent_by_staff_id and source.direction == "out" and source.author_type == "brand":
        # A synchronous send may arrive before its brand contact was observed by webhook.
        if source.kind == "comment_thread":
            message.contact_id = contact.id
    elif (message.direction, message.author_type, message.contact_id) != (
        source.direction,
        source.author_type,
        contact.id,
    ):
        raise InvalidEvent("message_identity_conflict")
    if relationship:
        if message.comment_parent_known and message.comment_parent_id != relationship[0]:
            raise InvalidEvent("comment_parent_conflict")
        if (
            message.comment_root_id
            and relationship[1]
            and message.comment_root_id != relationship[1]
        ):
            raise InvalidEvent("comment_root_conflict")
        message.comment_parent_known = True
        message.comment_parent_id = relationship[0]
        message.comment_root_id = relationship[1] or message.comment_root_id
    message.is_redelivery = message.is_redelivery or source.is_redelivery
    message.sources_json = sorted(set(message.sources_json or []) | {origin})
    if origin in {"history", "csv"}:
        return "unchanged_messages", 0
    if message.content_observed_at and observed_at < message.content_observed_at:
        return "unchanged_messages", 0
    if (
        source.edited_at is not None
        and message.edited_at is not None
        and source.edited_at < message.edited_at
    ):
        return "unchanged_messages", 0
    if message.text == source.text and message.attachments_json == source.attachments_json:
        if origin == "poll":
            message.content_observed_at = observed_at
        if source.edited_at is not None and (
            message.edited_at is None or source.edited_at > message.edited_at
        ):
            message.edited_at = source.edited_at
            message.content_observed_at = observed_at
            return "updated_messages", 0
        return "unchanged_messages", 0
    message.content_observed_at = observed_at
    message.text = source.text
    message.attachments_json = source.attachments_json
    message.edited_at = source.edited_at or received_at
    if message.direction == "in":
        # 編輯使舊分流失效；撤銷租約可阻止在途的舊結果覆蓋新內容。
        session.execute(
            update(InboundJob)
            .where(InboundJob.message_id == message.id, InboundJob.task == "classify")
            .values(status="pending", error=None, lease_id=None, lease_until=None)
        )
    return "updated_messages", 0


def csv_message(session, account, source, provenance):
    """僅供已授權 CSV 確認服務；不加入對外 webhook envelope 的來源選項。"""
    if account.platform == "line" or source.kind != "comment_thread":
        raise InvalidEvent("comments_only", 410)
    matches = list(
        session.scalars(
            select(Message)
            .join(Thread)
            .where(
                Thread.account_id == account.id,
                Thread.kind == source.kind,
                Message.external_id == source.external_id,
            )
            .limit(2)
        )
    )
    if len(matches) > 1:
        raise InvalidEvent("message_identity_ambiguous")
    if matches:
        existing = matches[0]
        if (existing.text, existing.sent_at, existing.direction) != (
            source.text,
            source.sent_at,
            source.direction,
        ):
            raise InvalidEvent("csv_existing_content_conflict")
        # 去重先於對話／聯絡人建立，避免 CSV 的舊對話 ID 產生空殼資料。
        existing.sources_json = sorted(set(existing.sources_json or []) | {"csv"})
        return "unchanged_messages"
    contact = session.scalar(
        select(Contact).where(
            Contact.brand_id == account.brand_id,
            Contact.platform == account.platform,
            Contact.external_id == source.contact.external_id,
        )
    )
    if contact is None:
        contact = _contact(session, account, source)

    thread = _thread(session, account, contact, source)
    now = utc_now()
    outcome, _jobs = _message(session, contact, thread, source, now, "csv", now)
    session.add(
        RawEvent(
            platform=account.platform,
            brand_id=account.brand_id,
            account_external_id=account.external_id,
            external_id="csv:" + str(account.id) + ":" + source.kind + ":" + source.external_id,
            signature_ok=False,
            source="csv",
            processed=True,
            payload_json={"provenance": provenance, "message": source.model_dump(mode="json")},
        )
    )
    session.flush()
    return outcome


def _process(
    session: Session, account: Account, event: EventInput, raw: RawEvent
) -> dict[str, int]:
    counts = {
        "created_messages": 0,
        "updated_messages": 0,
        "unchanged_messages": 0,
        "queued_jobs": 0,
    }
    for source in event.messages:
        if source.is_redelivery:
            raise InvalidEvent("redelivery_platform_mismatch")
        contact = _contact(session, account, source)
        thread = _thread(session, account, contact, source)
        observed = event.observed_at or source.edited_at or raw.received_at
        outcome, jobs = _message(
            session, contact, thread, source, raw.received_at, event.source, observed
        )
        counts[outcome] += 1
        counts["queued_jobs"] += jobs
        session.flush()
        if source.kind == "comment_thread" and source.post_external_id:
            comment_threads.regroup(session, account.id, source.post_external_id)
    return counts


def _validate_poll(session, event, account):
    from app.services.meta_api import require_run

    # Threads 不經 Meta 呼叫配額，也就沒有呼叫紀錄；其餘租約、貼文與時間範圍檢查相同。
    threads = event.platform in {"threads", "youtube"}
    if (
        event.platform not in {"instagram", "facebook", "threads", "youtube"}
        or event.signature_ok
        or not event.poll_run_id
        or bool(event.poll_call_id) == threads
        or not event.external_id.startswith("poll:")
        or event.references
    ):
        raise InvalidEvent("invalid_poll_source")
    try:
        state = require_run(session, event.poll_run_id, utc_now())
    except HTTPException:
        raise InvalidEvent("poll_lease_expired", 409) from None
    call = None if threads else session.get(MetaApiCall, event.poll_call_id)
    post = session.get(Post, state.post_id) if state.post_id else None
    if post is None or state.account_id != account.id:
        raise InvalidEvent("invalid_poll_call")
    if not threads and (
        call is None
        or call.run_id != state.run_id
        or call.account_id != account.id
        or call.source != "poll"
        or call.http_status != 200
        or call.operation not in {"comments", "replies"}
    ):
        raise InvalidEvent("invalid_poll_call")
    if any(
        m.kind != "comment_thread"
        or m.thread_external_id != post.external_id
        or m.post_external_id != post.external_id
        for m in event.messages
    ):
        raise InvalidEvent("poll_post_mismatch")
    if (
        state.window_end is None
        or any(
            (state.window_start is not None and m.sent_at < state.window_start)
            or m.sent_at >= state.window_end for m in event.messages
        )
    ):
        raise InvalidEvent("poll_outside_window")
    event.observed_at = utc_now() if threads else call.created_at


def events(
    session: Session, body: bytes, expected_source: str = "webhook", settings=None
) -> Outcome:
    # Retired transports must not create even a raw-event record through internal ingress.
    try:
        candidate = json.loads(body)
    except (ValueError, TypeError):
        candidate = {}
    messages = candidate.get("messages") if isinstance(candidate, dict) else None
    if isinstance(candidate, dict) and (
        expected_source == "history"
        or candidate.get("source") == "history"
        or candidate.get("platform") == "line"
        or candidate.get("references")
        or any(
            isinstance(m, dict) and m.get("kind") == "dm"
            for m in (messages if isinstance(messages, list) else [])
        )
    ):
        raise HTTPException(410, "僅接收貼文留言")
    status = 200
    counts = {}
    brand_id = None
    with session.begin():
        raw, parsed = _save_raw(session, body, expected_source)
        if raw.error == data_retention.REMOVED_EVENT:
            # 平台重送已過保留期的舊事件：視為已處理，不重建留言、聯絡人或通知。
            result = IngestResult(raw_event_id=raw.id, processed=True, error=raw.error)
            return Outcome(status=200, result=result)
        try:
            # 錯誤只回滾訊息批次，外層保留原始事件與診斷碼。
            with session.begin_nested():
                event = EventInput.model_validate(parsed)
                if event.source != expected_source:
                    raise InvalidEvent("source_mismatch", 403)
                if expected_source == "webhook" and not event.signature_ok:
                    raise InvalidEvent("signature_invalid", 403)
                account = _account(session, raw)
                if expected_source == "poll":
                    _validate_poll(session, event, account)
                brand_id = account.brand_id
                counts = _process(session, account, event, raw)
        except ValidationError:
            status, raw.error = 422, "invalid_payload"
        except InvalidEvent as error:
            status, raw.error = error.status, error.code
        except Exception as error:
            log_failure("mwb.ingest", "ingest_events_failed", error)
            # SQL 與第三方例外可能含原文或機密；保存固定診斷碼即可。
            status, raw.error = 503, "processing_failed"
        else:
            raw.processed = True
        raw.brand_id = brand_id
        result = IngestResult(
            raw_event_id=raw.id, processed=raw.processed, error=raw.error, **counts
        )
        session.add(
            AuditLog(
                brand_id=raw.brand_id,
                actor="system:n8n",
                action="ingest.events" if raw.processed else "ingest.rejected",
                target_type="raw_event",
                target_id=raw.id,
                detail_json={"processed": raw.processed, "error": raw.error, **counts},
            )
        )
    return Outcome(status=status, result=result)
