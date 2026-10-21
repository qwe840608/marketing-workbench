"""Explicit neutral price fixtures for isolated acceptance only."""

from decimal import Decimal

from sqlalchemy import select

from app.models import PriceItem, PriceItemHistory

FIELDS = (
    "category", "keywords", "price", "unit", "conditions", "needs_human",
    "effective_from", "approved_by", "notes", "active",
)


def seed_prices(session, brand_id=1):
    for category, words, price in (
        ("標準方案", ["標準方案", "標準"], "2500.00"),
        ("客製方案", ["客製", "客製方案"], "3500.00"),
        ("基本方案", ["基本方案"], "2000.00"),
    ):
        if session.scalar(
            select(PriceItem).where(PriceItem.brand_id == brand_id, PriceItem.category == category)
        ):
            continue
        item = PriceItem(
            brand_id=brand_id,
            category=category,
            keywords=words,
            price=price,
            unit="項",
            active=False,
            needs_human=True,
            notes="隔離測試，非實際報價",
        )
        session.add(item)
        session.flush()

        session.add(
            PriceItemHistory(
                price_item_id=item.id,
                changed_by=None,
                before_json={},
                after_json=snapshot(item),
            )
        )


def snapshot(row):
    data = {name: getattr(row, name) for name in FIELDS}
    data.update(
        id=row.id,
        brand_id=row.brand_id,
        version=row.version,
        archived=row.archived,
    )
    data["price"] = format(Decimal(row.price), ".2f")
    data["effective_from"] = row.effective_from.isoformat() if row.effective_from else None
    return data
