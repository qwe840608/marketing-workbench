"""只接收 Meta 官方帳號識別資料；平台憑證不傳入此程序。"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import Settings
from app.db import build_engine, session_factory
from app.services.accounts import register_meta_test_accounts


def main():
    settings = Settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--brand", default=settings.registration_brand_slug)
    args = parser.parse_args()
    if not args.brand:
        parser.error("請指定 --brand 或 REGISTRATION_BRAND_SLUG")
    info = json.load(sys.stdin)
    engine = build_engine(settings)
    try:
        with session_factory(engine).begin() as session:
            accounts = register_meta_test_accounts(session, info, args.brand)
            print(json.dumps({"registered": len(accounts)}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Meta 測試帳號登記失敗；未輸出輸入或內部例外。", file=sys.stderr)
        sys.exit(1)
