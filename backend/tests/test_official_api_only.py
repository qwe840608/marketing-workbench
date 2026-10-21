"""API-only provider contracts and reversible configuration migration."""

import importlib
import sqlite3
from datetime import timedelta

import pytest
from ai_fixtures import ai_data as ai_data
from ai_fixtures import classified_data as classified_data
from ai_fixtures import historical_draft
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import select

from app.config import REPO_ROOT
from app.models import Account, AIRun, AuditLog, Draft, Post, Setting
from app.models.base import utc_now
from app.models.ideation import IdeationReport, VideoScript
from app.schemas.ai import AISettings
from app.schemas.ideation import GenerateReport
from app.services import ai

migration = importlib.import_module("migrations.versions.0021_official_api_only")


@pytest.mark.parametrize("provider", ai.PROVIDERS)
def test_only_official_provider_contracts(provider):
    assert GenerateReport(provider=provider, post_ids=[1]).provider == provider
    assert (
        AISettings(manual_provider=provider, background_provider=provider).manual_provider
        == provider
    )
    assert ai.PROVIDERS == ("gemini_api", "openai_api", "anthropic_api")


@pytest.mark.parametrize("provider", ai.PROVIDERS)
def test_official_providers_accepted_by_http_endpoints(client, ai_data, settings, provider):
    name = provider.removesuffix("_api")
    setattr(settings, name + "_api_key", SecretStr("isolated-test-key"))
    setattr(settings, name + "_model", "isolated-test-model")
    brand, thread = ai_data["brand_id"], ai_data["thread_id"]
    url = f"/api/ai/settings?brand_id={brand}"
    response = client.get(url)
    assert response.status_code == 200
    assert [item["provider"] for item in response.json()["options"]] == list(ai.PROVIDERS)
    config = response.json()["config"]
    config.update(manual_provider=provider, background_provider=provider)
    response = client.put(url, json=config)
    assert response.status_code == 200
    assert response.json()["config"]["manual_provider"] == provider
    assert response.json()["config"]["background_provider"] == provider
    assert client.post(f"/api/drafts/threads/{thread}", json={}).status_code == 404
    with client.app.state.session_factory.begin() as session:
        account = Account(brand_id=brand, platform="facebook", external_id="ideaui-fb",
                          name="隔離帳號")
        session.add(account)
        session.flush()
        post = Post(account_id=account.id, external_id="ideaui-api", caption="隔離貼文",
                    media_type="POST", published_at=utc_now() - timedelta(days=1))
        session.add(post)
        session.flush()
        post_id = post.id
    response = client.post(f"/api/ideation/reports?brand_id={brand}",
                           json={"provider": provider, "post_ids": [post_id]})
    assert response.status_code == 202
    assert response.json()["provider"] == provider


@pytest.mark.parametrize("provider", migration.RETIRED_PROVIDERS)
def test_retired_provider_requests_return_422(client, ai_data, monkeypatch, provider):
    monkeypatch.setattr(ai.providers, "call_api", lambda *a: pytest.fail("must not call model"))
    brand = ai_data["brand_id"]
    requests = [
        ("post", f"/api/ideation/reports?brand_id={brand}", {"provider": provider}),
        ("put", f"/api/ai/settings?brand_id={brand}", {"manual_provider": provider}),
        ("put", f"/api/ai/settings?brand_id={brand}", {"background_provider": provider}),
        ("post", f"/api/ai/keys/{provider}/test", {}),
        ("put", f"/api/ai/keys/{provider}", {"receipt": "x" * 43}),
    ]
    for method, url, body in requests:
        response = getattr(client, method)(url, json=body)
        assert response.status_code == 422, response.text
    assert client.delete(f"/api/ai/keys/{provider}?version=0").status_code == 422


def snapshot(path):
    with sqlite3.connect(path) as conn:
        return {
            table: conn.execute(f'SELECT * FROM "{table}" ORDER BY id').fetchall()
            for table in (
                "ai_runs",
                "drafts",
                "ideation_reports",
                "video_scripts",
                "audit_log",
                "accounts",
            )
        }


@pytest.mark.parametrize("edited", [False, True])
@pytest.mark.migration
def test_migration_clears_settings_preserves_history_and_downgrades(
    client, ai_data, settings, edited
):
    cfg = Config(str(REPO_ROOT / "backend/alembic.ini"))
    response = historical_draft(client, ai_data)
    assert response.status_code == 200
    # 先在符合目前程式的結構建立歷史資料，再以舊結構驗證 0021 轉換。
    command.downgrade(cfg, "0020")
    old = migration.RETIRED_PROVIDERS
    expected = {
        "ai.brand.1": {"manual_provider": old[0], "background_provider": old[1]},
        "ai.workspace": {"providers": [{"default_provider": old[2]}], "note": old[0]},
        "auto_draft.default": {"provider": old[1], "enabled": True},
        "ideation.default": {"provider": old[2]},
        "untouched": {"provider": "openai_api"},
        "ai.default_provider": old[0],
    }
    with client.app.state.session_factory.begin() as session:
        for key, value in expected.items():
            session.add(Setting(key=key, value_json=value))
        for row in session.scalars(select(AIRun)):
            row.provider = old[0]
        for row in session.scalars(select(Draft)):
            row.provider = old[1]
        now = utc_now()
        report = IdeationReport(
            brand_id=ai_data["brand_id"],
            meeting_at=now,
            start_at=now - timedelta(days=1),
            end_at=now,
            trigger="manual",
            provider=old[2],
            status="ready",
        )
        session.add(report)
        session.flush()
        session.add(
            VideoScript(
                brand_id=report.brand_id,
                report_id=report.id,
                topic_index=0,
                title="test",
                content_json={},
                review_json={},
                provider=old[1],
                model="historical",
            )
        )
        session.add(
            AuditLog(
                actor="test", action="test", target_type="test", detail_json={"provider": old[0]}
            )
        )
    before = snapshot(settings.database_path)
    with client.app.state.session_factory() as session:
        original = {r.key: (r.value_json, r.version) for r in session.scalars(select(Setting))}
    command.upgrade(cfg, "0021")
    assert snapshot(settings.database_path) == before
    upgraded = {
        "ai.brand.1": {"manual_provider": None, "background_provider": None},
        "ai.workspace": {"providers": [{"default_provider": None}], "note": old[0]},
        "auto_draft.default": {"provider": None, "enabled": True},
        "ideation.default": {"provider": None},
        "untouched": {"provider": "openai_api"},
        "ai.default_provider": None,
    }
    with client.app.state.session_factory.begin() as session:
        for key, value in upgraded.items():
            row = session.scalar(select(Setting).where(Setting.key == key))
            assert row.value_json == value
            assert row.version == original[key][1] + (key != "untouched")
        if edited:
            row = session.scalar(select(Setting).where(Setting.key == "ai.brand.1"))
            row.value_json = {
                "manual_provider": "openai_api",
                "background_provider": None,
                "monthly_budget_usd": 12,
            }
    command.downgrade(cfg, "0020")
    assert snapshot(settings.database_path) == before
    with client.app.state.session_factory() as session:
        for key, (value, version) in original.items():
            row = session.scalar(select(Setting).where(Setting.key == key))
            if edited and key == "ai.brand.1":
                assert row.value_json == {
                    "manual_provider": "openai_api",
                    "background_provider": old[1],
                    "monthly_budget_usd": 12,
                }
                assert row.version > version
            else:
                assert (row.value_json, row.version) == (value, version)
    command.upgrade(cfg, "0021")


def test_cleared_provider_defaults_are_readable_and_background_stays_disabled(client, ai_data):
    with client.app.state.session_factory.begin() as session:
        session.add(
            Setting(
                key=f"ai.brand.{ai_data['brand_id']}",
                value_json={"manual_provider": None, "background_provider": None},
            )
        )
    response = client.get(f"/api/ai/settings?brand_id={ai_data['brand_id']}")
    assert response.status_code == 200
    assert response.json()["config"]["manual_provider"] is None
    assert response.json()["config"]["background_provider"] is None


@pytest.mark.migration
def test_migration_ignores_native_sqlite_number(settings, migrated):
    cfg = Config(str(REPO_ROOT / "backend/alembic.ini"))
    command.downgrade(cfg, "0020")
    now = utc_now().isoformat()
    with sqlite3.connect(settings.database_path) as conn:
        conn.execute(
            "INSERT INTO settings(key, value_json, version, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("numeric_setting", 0.25, 1, now, now),
        )
    command.upgrade(cfg, "0021")
    command.downgrade(cfg, "0020")
    with sqlite3.connect(settings.database_path) as conn:
        assert conn.execute("SELECT value_json, version FROM settings").fetchall() == [(0.25, 1)]
