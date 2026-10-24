"""只能在主機終端機設定密碼；不接受命令列密碼，避免落入歷史紀錄。"""

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from pydantic import SecretStr

from app.config import Settings
from app.db import build_engine, session_factory
from app.services.passwords import create_admin, create_first_brand, set_password


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="設定本機後台帳號密碼")
    parser.add_argument("username")
    parser.add_argument(
        "--create-admin", action="store_true", help="僅新安裝空白使用者表可建立首次管理員"
    )
    parser.add_argument("--brand", help="首次管理員一併建立的品牌名稱；省略時會詢問")
    args = parser.parse_args()
    if not sys.stdin.isatty():
        print("請在互動式終端機執行。")
        return 1
    brand_name = args.brand
    if args.create_admin and brand_name is None:
        brand_name = input("品牌名稱（例如自己的頻道或品牌名稱）：")
    first = SecretStr(getpass.getpass("新密碼（12–128 字元，不顯示輸入）："))
    second = SecretStr(getpass.getpass("再輸入一次："))
    if first != second:
        print("兩次密碼不一致，未變更。")
        return 1
    engine = build_engine(Settings())
    try:
        with session_factory(engine).begin() as session:
            if args.create_admin:
                staff = create_admin(session, args.username, first)
                brand = create_first_brand(session, brand_name)
                message = f"已建立管理員帳號「{staff.username}」，可用此帳號登入。"
                if brand is not None:
                    message += f"已建立品牌「{brand.name}」。"
            else:
                set_password(session, args.username, first)
                message = "密碼已更新，該帳號的既有登入已失效。"
        print(message)
        return 0
    except ValueError as error:
        print(str(error))
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
