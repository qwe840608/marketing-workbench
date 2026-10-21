"""本機管理員為指定貼文設定會自動到期的抓取頻率覆寫，不修改平台貼文。"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import Settings
from app.db import build_engine, session_factory
from app.services.posts import set_schedule_override


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("post_id", type=int)
    parser.add_argument("tier", choices=["hourly", "daily", "weekly"])
    parser.add_argument("--hours", type=int, default=2)
    args = parser.parse_args()
    engine = build_engine(Settings())
    try:
        with session_factory(engine).begin() as session:
            set_schedule_override(session, args.post_id, args.tier, args.hours)
        print("貼文排程覆寫已儲存，到期後自動恢復品牌設定或預設頻率。")
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("排程設定失敗；未輸出內部例外。", file=sys.stderr)
        sys.exit(1)
