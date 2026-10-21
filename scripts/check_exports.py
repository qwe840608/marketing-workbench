"""T1-12 隔離驗收：真實背景排程、原子更新與兩種 Word；不連接任何外部帳號。"""

from runtime_tmp import cleanup, output_dir, runtime_check, temporary_dir

import json
import os
import secrets
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


@runtime_check
def main():
    from alembic import command
    from alembic.config import Config
    from app.config import Settings
    from app.db import build_engine, session_factory
    from app.main import create_app
    from app.models import (
        Account,
        Brand,
        Contact,
        Message,
        MetricSnapshot,
        Post,
        Staff,
        Thread,
    )
    from app.models.base import utc_now
    from app.services.passwords import hash_password
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    folder = temporary_dir()
    os.environ["DATABASE_PATH"] = str(folder / "test.db")
    os.environ["EXPORT_ROOT"] = str(folder / "export")
    os.environ["OBSIDIAN_ROOT"] = str(folder / "obsidian")
    os.environ["LOG_PATH"] = str(folder / "test.jsonl")
    settings = Settings(
        _env_file=None,
        database_path=folder / "test.db",
        export_root=folder / "export",
        obsidian_root=folder / "obsidian",
        log_path=folder / "test.jsonl",
        app_origin="http://testserver",
        allowed_hosts=["testserver"],
        export_worker_enabled=True,
        scheduler_enabled=False,
        receive_health_worker_enabled=False,
        session_cookie_secure=False,
    )
    command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
    engine = build_engine(settings)
    cleanup(engine.dispose)
    factory = session_factory(engine)
    password = SecretStr(secrets.token_urlsafe(32))
    now = utc_now()
    with factory.begin() as db:
        brand = Brand(slug="export-test", name="匯出驗收品牌（隔離測試）")
        db.add(brand)
        db.flush()
        brand_id = brand.id
        account = Account(
            brand_id=brand_id, platform="facebook", external_id="export-test", name="匯出驗收帳號"
        )
        contact = Contact(
            brand_id=brand_id,
            platform="facebook",
            external_id="export-user",
            display_name="測試用戶",
        )
        db.add_all([account, contact])
        db.flush()
        thread = Thread(
            brand_id=brand_id,
            account_id=account.id,
            external_id="export-thread",
            contact_id=contact.id,
            kind="comment_thread",
            stage="booked",
            booking_date=now.date(),
            booking_units=2,
        )
        db.add(thread)
        db.flush()
        thread_id = thread.id
        for i in range(8):
            message = Message(
                thread_id=thread_id,
                contact_id=contact.id,
                external_id=f"export-{i}",
                direction="in" if i % 2 == 0 else "out",
                author_type="fan" if i % 2 == 0 else "brand",
                text=f"[隔離驗收 {i + 1}] "
                + (
                    "想了解服務與預約方式，可以先提供照片讓專人確認嗎？\n"
                    if i % 2 == 0
                    else "請提供方便聯繫的時段，實際預約由專人確認，不保證尚未確認的時間。\n"
                )
                * 3,
                sent_at=now - timedelta(minutes=8 - i),
            )
            db.add(message)
            db.flush()
        message_id = message.id
        for i in range(3):
            post = Post(
                account_id=account.id,
                external_id=f"export-post-{i}",
                caption=f"[隔離驗收] 貼文 {i + 1}：服務流程與常見問題",
                media_type="image",
                published_at=now - timedelta(minutes=i),
                permalink=f"https://example.com/posts/{i}",
            )
            db.add(post)
            db.flush()
            db.add(
                MetricSnapshot(
                    post_id=post.id,
                    captured_at=now,
                    views=100 * (i + 1),
                    reach=None if i == 0 else 50 * (i + 1),
                    likes=0,
                    comments=i,
                )
            )
        thread.post_id = post.id
        db.add(
            Staff(
                username="export-test",
                display_name="匯出驗收",
                role="admin",
                password_hash=hash_password(password),
            )
        )
    with TestClient(create_app(settings)) as client:
        csrf = client.get("/api/auth/csrf").json()["csrf_token"]
        logged = client.post(
            "/api/auth/login",
            json={"username": "export-test", "password": password.get_secret_value()},
            headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        )
        assert logged.status_code == 200
        client.headers.update(
            {"Origin": "http://testserver", "X-CSRF-Token": logged.json()["csrf_token"]}
        )
        assert client.post("/api/exports/sync").json()["ok"]
        user_file = next(settings.export_root.glob("*/users/*/*.md"))
        started = time.monotonic()
        with factory.begin() as db:
            db.get(Message, message_id).text = "[隔離驗收] 修改後必須自動出現在 Markdown。"
        while "修改後必須自動" not in user_file.read_text(encoding="utf-8"):
            if time.monotonic() - started > 30:
                raise AssertionError("未在 30 秒內更新 Markdown")
            time.sleep(0.5)
        elapsed = round(time.monotonic() - started, 2)
        body = {
            "brand_id": brand_id,
            "start": str(now.date() - timedelta(days=1)),
            "end": str(now.date() + timedelta(days=1)),
        }
        for name, path, payload in [
            ("conversation", f"/api/exports/threads/{thread_id}/docx", {}),
            ("report", "/api/exports/report/docx", body),
        ]:
            response = client.post(path, json=payload)
            assert response.status_code == 200, response.status_code
            (output_dir() / f"{name}.docx").write_bytes(response.content)
        result = {
            "passed": True,
            "markdown_update_seconds": elapsed,
            "word_types": ["conversation", "report"],
            "folder": str(output_dir()),
        }
        (output_dir() / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=True))
    engine.dispose()


if __name__ == "__main__":
    main()
