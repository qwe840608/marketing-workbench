from fastapi import HTTPException
from sqlalchemy import or_, select

from app.models import Contact, Message, MetricSnapshot, Post, Thread
from app.services.access import BrandAccess


def _statement(access, model, brand_id=None):
    query = access.statement(model, brand_id)
    if model is Thread:
        return query.where(Thread.kind == "comment_thread")
    if model is Contact:
        return query.where(
            or_(
                Contact.id.in_(select(Thread.contact_id).where(Thread.kind == "comment_thread")),
                Contact.id.in_(
                    select(Message.contact_id).join(Thread).where(Thread.kind == "comment_thread")
                ),
            )
        )
    return query


def list_records(access: BrandAccess, model, brand_id: int | None, limit: int, offset: int):
    if brand_id is not None:
        access.require_brand(brand_id)
    query = _statement(access, model, brand_id).order_by(model.id).limit(limit).offset(offset)
    return list(access.session.scalars(query))


def get_record(access: BrandAccess, model, record_id: int):
    item = access.session.scalar(_statement(access, model).where(model.id == record_id))
    if item is None:
        raise HTTPException(404, "找不到資料")
    return item


def thread_messages(access: BrandAccess, thread_id: int, limit: int, offset: int):
    get_record(access, Thread, thread_id)
    return list(
        access.session.scalars(
            access.statement(Message)
            .where(Message.thread_id == thread_id)
            .order_by(Message.sent_at, Message.id)
            .limit(limit)
            .offset(offset)
        )
    )


def post_metrics(access: BrandAccess, post_id: int, limit: int, offset: int):
    get_record(access, Post, post_id)
    return list(
        reversed(
            list(
                access.session.scalars(
                    access.statement(MetricSnapshot)
                    .where(MetricSnapshot.post_id == post_id)
                    .order_by(MetricSnapshot.captured_at.desc(), MetricSnapshot.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
        )
    )
