"""Preview, then enable, the daily platform-data deletion; handle commenter deletion requests.

Run from the repository root: uv run --project backend python scripts/data_retention.py
Default prints how many rows the retention rules would delete now and writes nothing.
--enable turns the daily job on; run scripts/backup.ps1 first.
--find-commenter NAME lists matching commenters; --delete-contact ID previews everything that
commenter left and deletes it only with --apply. Never prints comment text.
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from app.config import Settings
    from app.db import build_engine, session_factory
    from app.services import data_retention, settings_store

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--enable", action="store_true", help="啟用每日刪除（先備份）")
    parser.add_argument("--find-commenter", metavar="NAME", help="依名稱找出留言者")
    parser.add_argument("--delete-contact", metavar="ID", type=int, help="預覽刪除某位留言者")
    parser.add_argument("--apply", action="store_true", help="與 --delete-contact 併用才刪除")
    args = parser.parse_args()
    settings = Settings()
    factory = session_factory(build_engine(settings))

    if args.find_commenter:
        with factory() as session:
            result = data_retention.find_contacts(session, args.find_commenter)
    elif args.delete_contact:
        # 預覽用唯讀連線；只有 --apply 才開寫入交易。
        with (factory.begin() if args.apply else factory()) as session:
            plan = data_retention.for_contact(session, args.delete_contact)
            result = {
                "contact_id": args.delete_contact,
                "would_delete": data_retention.counts(plan),
            }
            if args.apply:
                from app.services.posts import _begin_ingest

                result["deleted"] = data_retention.apply(session, plan)
                audit = _begin_ingest(session, "data.delete_request")
                audit.actor, audit.detail_json = "operator", result["deleted"]
    else:
        result = {
            "comment_retention_days": settings.comment_retention_days,
            "youtube_fresh_days": data_retention.YOUTUBE_FRESH_DAYS,
            "would_delete": data_retention.preview(factory, settings),
        }
        if args.enable:
            data_retention.enable(factory)
        with factory() as session:
            row = settings_store.get(session, data_retention.KEY)
            result["daily_job_enabled"] = bool(row and row.value_json.get("enabled"))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
