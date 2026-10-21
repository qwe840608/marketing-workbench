"""Local administration of the one-time queue; platform reads remain in the backend scheduler."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def main():
    from app.config import Settings
    from app.db import build_engine, session_factory
    from app.models import Staff
    from app.services import comment_backfill
    from app.services.access import BrandAccess
    from sqlalchemy import select

    parser = argparse.ArgumentParser(description="最近 90 天留言：建立一次性佇列或查看進度")
    parser.add_argument("action", choices=["start", "status"])
    parser.add_argument("--platform", choices=["facebook", "instagram"])
    args = parser.parse_args()
    engine = build_engine(Settings())
    try:
        with session_factory(engine)() as session:
            # 以第一個啟用中的管理員身分建立佇列；不寫死帳號名稱，自架者的管理員名稱各不相同。
            admin = session.scalar(
                select(Staff)
                .where(Staff.role == "admin", Staff.active.is_(True))
                .order_by(Staff.id)
            )
            if admin is None:
                raise RuntimeError("找不到啟用中的管理員")
            access = BrandAccess(session, admin)
            if args.action == "start":
                print(json.dumps(comment_backfill.start(access, platform=args.platform)))
            print(
                json.dumps(
                    comment_backfill.status(access, platform=args.platform),
                    ensure_ascii=True,
                    default=lambda value: value.isoformat(),
                )
            )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
