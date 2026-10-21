import pytest
from alembic import command
from alembic.config import Config
from message_fixtures import send_data as send_data
from sqlalchemy import select, text

from app.config import REPO_ROOT
from app.models import Setting


@pytest.mark.migration
def test_downgrade_cancels_waiting_rounds_and_removes_new_settings(client, send_data):
    d = send_data
    cfg = Config(str(REPO_ROOT / "backend/alembic.ini"))
    command.downgrade(cfg, "0027")
    with d["factory"].begin() as s:
        s.execute(
            text("INSERT INTO auto_draft_jobs "
                 "(created_at, updated_at, message_id, message_version, attempts, status, reason) "
                 "VALUES ('2026-01-01', '2026-01-01', :message, 1, 1, "
                 "'pending', 'provider_http_503')"),
            {"message": d["message"]},
        )
        s.add(
            Setting(
                key=f"ai.brand.{d['brand']}",
                value_json={
                    "manual_provider": "gemini_api",
                    "background_provider": "gemini_api",
                    "gemini_fallback_model": "backup",
                    "openai_fallback_model": "",
                    "anthropic_fallback_model": "",
                    "monthly_budget_usd": None,
                },
            )
        )
    command.downgrade(cfg, "0026")
    command.upgrade(cfg, "0027")
    with d["factory"]() as s:
        job = s.execute(text("SELECT status, reason FROM auto_draft_jobs")).one()
        assert job.status == "skipped" and job.reason == "retry_downgraded"
        setting = s.scalar(select(Setting).where(Setting.key == f"ai.brand.{d['brand']}"))
        assert not any(key.endswith("_fallback_model") for key in setting.value_json)
        assert setting.value_json["manual_provider"] == "gemini_api"
        assert setting.version == 2
