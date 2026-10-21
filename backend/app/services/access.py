from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Account,
    AdMetricDaily,
    AIRun,
    AuditLog,
    Brand,
    Classification,
    Contact,
    Draft,
    InboundJob,
    Message,
    MetricSnapshot,
    Notification,
    Post,
    PriceItem,
    PriceItemHistory,
    PublishPost,
    RawEvent,
    Staff,
    StaffBrand,
    Thread,
)


@dataclass(frozen=True)
class BrandAccess:
    session: Session
    staff: Staff

    def statement(self, model, brand_id: int | None = None):
        """所有領域讀取共用的品牌條件；未知資料表預設拒絕。"""
        query = select(model)
        if model is Brand:
            brand_column = Brand.id
        elif model in (
            Account,
            Contact,
            Thread,
            PriceItem,
            AIRun,
            Notification,
            RawEvent,
            AuditLog,
            PublishPost,
        ):
            brand_column = model.brand_id
        elif model in (Post, AdMetricDaily):
            query = query.join(Account, model.account_id == Account.id)
            brand_column = Account.brand_id
        elif model in (Message, Draft):
            query = query.join(Thread, model.thread_id == Thread.id)
            brand_column = Thread.brand_id
        elif model is MetricSnapshot:
            query = query.join(Post, MetricSnapshot.post_id == Post.id).join(
                Account, Post.account_id == Account.id
            )
            brand_column = Account.brand_id
        elif model in (Classification, InboundJob):
            query = query.join(Message, model.message_id == Message.id).join(
                Thread, Message.thread_id == Thread.id
            )
            brand_column = Thread.brand_id
        elif model is PriceItemHistory:
            query = query.join(PriceItem, PriceItemHistory.price_item_id == PriceItem.id)
            brand_column = PriceItem.brand_id
        else:
            raise ValueError("資料表未定義品牌存取規則")

        if self.staff.role != "admin":
            visible = select(StaffBrand.brand_id).where(StaffBrand.staff_id == self.staff.id)
            query = query.where(brand_column.in_(visible))
        if brand_id is not None:
            query = query.where(brand_column == brand_id)
        return query

    def require_brand(self, brand_id: int, *, write: bool = False) -> Brand:
        brand = self.session.scalar(self.statement(Brand).where(Brand.id == brand_id))
        if brand is None:
            raise HTTPException(404, "找不到資料")
        if write and self.staff.role not in {"admin", "marketing"}:
            raise HTTPException(403, "此帳號僅能檢視資料")
        return brand
