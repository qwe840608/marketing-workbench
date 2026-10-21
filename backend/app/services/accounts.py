import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import ensure_write
from app.models import Account, AuditLog, Brand


def register_meta_test_accounts(session: Session, info: dict, brand_slug: str) -> list[Account]:
    ensure_write(session)
    brand = session.scalar(select(Brand).where(Brand.slug == brand_slug))
    if brand is None:
        raise ValueError("指定品牌不存在")
    accounts = []
    for platform in ("facebook", "instagram"):
        item = info[platform]
        if re.fullmatch(r"\d+", item["id"]) is None or not 1 <= len(item["name"]) <= 190:
            raise ValueError("Meta 官方帳號資訊無效")
        rows = list(
            session.scalars(
                select(Account).where(
                    Account.platform == platform, Account.external_id == item["id"]
                )
            )
        )
        if len(rows) > 1 or any(row.brand_id != brand.id for row in rows):
            raise ValueError("Meta 帳號已有衝突的品牌設定")
        if rows:
            accounts.append(rows[0])
            continue
        account = Account(
            brand_id=brand.id,
            platform=platform,
            external_id=item["id"],
            name=item["name"],
            token_ref="META_PAGE_ACCESS_TOKEN",
            status="disconnected",
        )
        session.add(account)
        session.flush()
        session.add(
            AuditLog(
                brand_id=brand.id,
                actor="local:setup",
                action="account.register",
                target_type="account",
                target_id=account.id,
                detail_json={"platform": platform, "test_account": True},
            )
        )
        accounts.append(account)
    return accounts
