"""本機 CLI 與網頁 AI 撰寫按鈕移除後的行為；全部使用合成資料與假 HTTP，不呼叫任何真實 AI。"""

import json
from datetime import timedelta
from unittest.mock import Mock

import pytest
from ai_fixtures import ai_data as ai_data
from ai_fixtures import classified_data as classified_data
from ai_fixtures import historical_draft
from alembic import command as migrate
from alembic.config import Config
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, inspect, select, text
from test_stage3 import access, complete, idea_payload
from test_stage3 import stage as stage

from app.api.permissions import ROUTE_POLICY
from app.config import REPO_ROOT
from app.main import create_app
from app.models import AIRun, AuditLog, CommentPoll, Draft, Setting, Staff
from app.models.base import utc_now
from app.models.ideation import IdeationReport
from app.schemas.ai import AISettings
from app.schemas.ideation import GenerateReport
from app.services import ai, auth, comment_poll, ideation
from app.services.ai import providers

CLI_PROVIDERS = ("codex_cli", "claude_cli", "agy_cli")


def web_client(stage):
    from fastapi.testclient import TestClient

    with stage.factory.begin() as session:
        session.get(Staff, stage.user).password_hash = "isolated-session-fixture"
        credentials = auth.issue_session(session, stage.settings, stage.user)
    client = TestClient(create_app(stage.settings))
    client.cookies.set(auth.COOKIE_NAME, credentials.token)
    client.headers.update({"origin": "http://testserver", "x-csrf-token": credentials.csrf_token})
    return client


def brand_row(client, brand_id, values):
    with client.app.state.session_factory.begin() as session:
        session.add(Setting(key=f"ai.brand.{brand_id}", value_json=values))


@pytest.mark.parametrize("provider", CLI_PROVIDERS)
def test_cli_values_in_saved_settings_read_as_unset_without_writing(client, ai_data, provider):
    brand_id = ai_data["brand_id"]
    saved = {"default_provider": provider, "manual_provider": provider,
             "background_provider": "gemini_api", "monthly_budget_usd": 5}
    brand_row(client, brand_id, saved)
    path = f"/api/ai/settings?brand_id={brand_id}"
    view = client.get(path).json()
    assert view["config"]["default_provider"] is None
    assert view["config"]["manual_provider"] is None
    assert view["config"]["background_provider"] == "gemini_api"
    assert "draft_provider" not in view
    assert [item["provider"] for item in view["options"]] == list(ai.PROVIDERS)
    options = client.get(f"/api/ai/execution-options?brand_id={brand_id}").json()
    assert options["draft_provider"] == ""
    assert all(item["provider"] in ai.PROVIDERS for item in options["options"])
    with client.app.state.session_factory() as session:
        # 只在讀取時轉換，資料庫不做任何改寫。
        row = session.scalar(select(Setting).where(Setting.key == f"ai.brand.{brand_id}"))
        assert row.value_json == saved
        assert ai.config(session, brand_id, client.app.state.settings).default_provider is None
    # 舊值不擋預算儲存；儲存後才寫入「未設定」。
    response = client.put(path, json={**view["config"], "monthly_budget_usd": 20})
    assert response.status_code == 200
    assert response.json()["config"]["default_provider"] is None
    assert response.json()["config"]["monthly_budget_usd"] == 20


@pytest.mark.parametrize("provider", CLI_PROVIDERS)
def test_cli_values_are_rejected_when_saving_settings_or_creating_reports(
    client, ai_data, provider
):
    brand_id = ai_data["brand_id"]
    path = f"/api/ai/settings?brand_id={brand_id}"
    config = client.get(path).json()["config"]
    for field in ("default_provider", "manual_provider", "background_provider"):
        assert client.put(path, json={**config, field: provider}).status_code == 422
    assert client.post(
        f"/api/ideation/reports?brand_id={brand_id}", json={"provider": provider, "post_ids": [1]}
    ).status_code == 422
    with pytest.raises(ValidationError):
        GenerateReport(post_ids=[1], provider=provider)
    with pytest.raises(ValidationError):
        AISettings(default_provider=provider)
    assert GenerateReport(post_ids=[1], provider="agent").provider == "agent"


def test_without_any_api_key_every_option_is_unavailable_and_default_is_unset(
    client, ai_data, settings
):
    # 沒有任何 API 金鑰時，網頁預設改為「交給 Agent 撰寫」；後端只回報 API 都不可用。
    for name in ("gemini", "openai", "anthropic"):
        setattr(settings, name + "_api_key", None)
        setattr(settings, name + "_model", "")
    brand_id = ai_data["brand_id"]
    options = client.get(f"/api/ai/execution-options?brand_id={brand_id}").json()
    assert options["draft_provider"] == ""
    assert [item["available"] for item in options["options"]] == [False, False, False]
    view = client.get(f"/api/ai/settings?brand_id={brand_id}").json()
    assert not any(item["available"] for item in view["options"])
    assert all(item["reason"] for item in view["options"])


def test_legacy_local_cli_setting_row_does_not_add_options_or_change_defaults(client, ai_data):
    brand_id = ai_data["brand_id"]
    with client.app.state.session_factory.begin() as session:
        session.add(Setting(key="ai.local_cli", value_json={
            "draft_provider": "claude_cli", "marketing_allowed": True,
            "claude_cli": {"enabled": True, "executable": "claude", "timeout_seconds": 300},
        }))
    options = client.get(f"/api/ai/execution-options?brand_id={brand_id}").json()
    assert options["draft_provider"] == ""
    assert [item["provider"] for item in options["options"]] == list(ai.PROVIDERS)


def test_brand_default_provider_keeps_version_permissions_and_audit(client, ai_data):
    brand_id = ai_data["brand_id"]
    path = f"/api/ai/settings?brand_id={brand_id}"
    cfg = {**client.get(path).json()["config"], "default_provider": "openai_api"}
    saved = client.put(path, json=cfg)
    assert saved.status_code == 200
    assert saved.json()["config"]["default_provider"] == "openai_api"
    assert client.get(f"/api/ai/execution-options?brand_id={brand_id}").json()[
        "draft_provider"] == "openai_api"
    with client.app.state.session_factory() as session:
        audit = session.scalar(
            select(AuditLog).where(AuditLog.action == "ai.settings").order_by(AuditLog.id.desc())
        )
        assert audit.detail_json["default_provider"] == "openai_api"
    assert client.put(path, json=cfg).status_code == 409
    cleared = client.put(path, json={**saved.json()["config"], "default_provider": ""})
    assert cleared.status_code == 200
    assert client.get(f"/api/ai/execution-options?brand_id={brand_id}").json()[
        "draft_provider"] == ""
    config = client.get(path).json()["config"]
    assert client.put(path, json={**config, "default_provider": "invalid"}).status_code == 422
    with client.app.state.session_factory.begin() as session:
        session.scalar(select(Staff).where(Staff.username == "admin")).role = "viewer"
    assert client.put(path, json={**config, "default_provider": "openai_api"}).status_code == 403


REMOVED_ROUTES = [
    ("get", "/api/ai/local-cli"),
    ("put", "/api/ai/local-cli"),
    ("get", "/api/ai/local-cli/models"),
    ("get", "/api/ai/local-cli/active"),
    ("get", "/api/ai/local-cli/update"),
    ("post", "/api/ai/local-cli/update"),
    ("post", "/api/ideation/reports/1/ideas/regenerate"),
    ("post", "/api/ideation/reports/1/ideas/0/extend"),
    ("post", "/api/ideation/reports/1/scripts"),
    ("get", "/api/publish/ideation-preview?report_id=1&idea_index=0"),
    ("post", "/api/publish/posts/1/caption/retry"),
    ("post", "/api/publish/posts/1/caption/apply"),
]


@pytest.mark.parametrize("method,path", REMOVED_ROUTES)
def test_removed_routes_return_404_or_405(client, ai_data, monkeypatch, method, path):
    monkeypatch.setattr(ai, "run", lambda *a, **k: pytest.fail("must not call AI"))
    response = getattr(client, method)(path, **({} if method == "get" else {"json": {}}))
    assert response.status_code in {404, 405}, response.text


def test_route_policy_has_no_removed_endpoints_and_keeps_edit_and_script_view():
    # 路由與政策的一致性由 test_members 的路由盤點保證；這裡確認被移除與保留的項目。
    forbidden = ("local-cli", "caption/", "ideation-preview", "/ideas/regenerate", "/extend")
    assert not [key for key in ROUTE_POLICY if any(word in key[1] for word in forbidden)]
    assert ("POST", "/api/ideation/reports/{report_id}/scripts") not in ROUTE_POLICY
    for key in (("PUT", "/api/ideation/reports/{report_id}/ideas/{index}"),
                ("POST", "/api/ideation/reports/{report_id}/ideas/{index}/restore"),
                ("GET", "/api/ideation/reports/{report_id}/scripts"),
                ("GET", "/api/ideation/scripts/{script_id}"),
                ("PUT", "/api/ideation/scripts/{script_id}"),
                ("POST", "/api/publish/ideation-draft")):
        assert key in ROUTE_POLICY


def create_report(stage, provider):
    with stage.factory() as session:
        return ideation.create(
            access(stage, session), stage.brand,
            GenerateReport(post_ids=[stage.post], provider=provider,
                           start_at=utc_now() - timedelta(days=7), end_at=utc_now()),
            stage.factory, stage.settings,
        )


def finish_comment_sync(stage):
    with stage.factory.begin() as session:
        state = session.scalar(select(CommentPoll).where(CommentPoll.post_id == stage.post))
        state.last_completed_at = utc_now()
        state.manual_requested = False
        state.last_error = None


def test_agent_choice_stops_at_awaiting_ideas_and_never_calls_ai(stage, monkeypatch):
    monkeypatch.setattr(comment_poll, "wake", Mock())
    run, api = Mock(side_effect=AssertionError("AI forbidden")), Mock(
        side_effect=AssertionError("API forbidden"))
    monkeypatch.setattr(ai, "run", run)
    monkeypatch.setattr(providers, "call_api", api)
    created = create_report(stage, "agent")
    rid = created["id"]
    assert created["provider"] == "agent" and created["status"] == "syncing_comments"
    assert created["data"].get("source") is None
    finish_comment_sync(stage)
    ideation.process(stage.factory, stage.settings, rid)
    with stage.factory() as session:
        row = session.get(IdeationReport, rid)
        assert row.status == "awaiting_ideas" and row.error is None and row.lease_until is None
        assert row.provider == "agent" and "ideas" not in row.data_json
        assert row.data_json["groups"] and row.data_json["awaiting_ideas_at"]
        assert row.data_json["brand_context"]["brand"] == "TEST 隔離驗收"
        assert session.scalar(select(func.count()).select_from(AIRun).where(
            AIRun.task == "ideation")) == 0
        view = ideation.view(row)
        assert view["status"] == "awaiting_ideas" and view["can_retry"] is False
    run.assert_not_called()
    api.assert_not_called()


def test_web_agent_report_is_ready_for_an_agent_to_take_over(stage, monkeypatch):
    from app.services import agent_content

    monkeypatch.setattr(comment_poll, "wake", Mock())
    monkeypatch.setattr(ai, "run", Mock(side_effect=AssertionError("AI forbidden")))
    rid = create_report(stage, "agent")["id"]
    finish_comment_sync(stage)
    ideation.process(stage.factory, stage.settings, rid)
    with stage.factory() as session:
        waiting = agent_content.waiting_report(access(stage, session), rid)
        assert waiting.status == "awaiting_ideas"
        ideas = ideation.validate_ideas(idea_payload(waiting.data_json), waiting.data_json)
        assert len(ideas) == 15


def test_expired_agent_report_can_be_retried_from_the_web(stage, monkeypatch):
    monkeypatch.setattr(comment_poll, "wake", Mock())
    monkeypatch.setattr(ai, "run", Mock(side_effect=AssertionError("AI forbidden")))
    rid = create_report(stage, "agent")["id"]
    finish_comment_sync(stage)
    ideation.process(stage.factory, stage.settings, rid)
    with stage.factory.begin() as session:
        row = session.get(IdeationReport, rid)
        row.data_json = {**row.data_json,
                         "awaiting_ideas_at": (utc_now() - timedelta(hours=25)).isoformat()}
    assert rid not in ideation.schedule(stage.factory, stage.settings)
    with stage.factory() as session:
        row = session.get(IdeationReport, rid)
        assert row.status == "failed"
        assert ideation.view(row)["can_retry"] is True
        assert ideation.retry(access(stage, session), rid, stage.settings)["status"] in {
            "pending", "syncing_comments"}
    finish_comment_sync(stage)
    ideation.process(stage.factory, stage.settings, rid)
    with stage.factory() as session:
        assert session.get(IdeationReport, rid).status == "awaiting_ideas"


def test_api_choice_still_calls_the_api_through_fake_http(stage, monkeypatch):
    stage.settings.gemini_api_key = SecretStr("isolated-key")
    stage.settings.gemini_model = "isolated"
    stage.settings.gemini_paid_tier = True
    monkeypatch.setattr(comment_poll, "wake", Mock())
    calls = []

    def fake_http(provider, model, prompt, settings, fallback):
        calls.append((provider, model))
        payload = idea_payload(json.loads(prompt)["evidence"])
        return providers.Result(json.dumps(payload, ensure_ascii=False), model, 42, 18)

    monkeypatch.setattr(providers, "call_api", fake_http)
    created = create_report(stage, "gemini_api")
    assert created["provider"] == "gemini_api"
    finish_comment_sync(stage)
    ideation.process(stage.factory, stage.settings, created["id"])
    assert calls == [("gemini_api", "isolated")]
    with stage.factory() as session:
        row = session.get(IdeationReport, created["id"])
        assert row.status == "ready" and len(row.data_json["ideas"]) == 15
        run = session.scalar(select(AIRun).where(AIRun.task == "ideation"))
        assert run.provider == "gemini_api" and run.mode == "api" and run.ok
        assert (run.tokens_in, run.tokens_out) == (42, 18)


def test_ai_run_rejects_any_non_api_provider(stage):
    for provider in (*CLI_PROVIDERS, "agent", "unknown"):
        result = ai.run("ideation", "prompt", "manual", factory=stage.factory,
                        settings=stage.settings, brand_id=stage.brand, provider=provider)
        assert result.error == "provider_unavailable"


def test_legacy_cli_reports_remain_readable_and_cannot_be_retried(stage):
    now = utc_now()
    rows = []
    with stage.factory.begin() as session:
        for provider, status in (("codex_cli", "ready"), ("claude_cli", "failed"),
                                 ("agy_cli", "pending")):
            row = IdeationReport(
                brand_id=stage.brand, meeting_at=now, start_at=now - timedelta(days=7),
                end_at=now, trigger="manual", provider=provider, status=status,
                error="文字模型未完成（cli_not_logged_in）" if status == "failed" else None,
                data_json={"topics": ["其他"], "ideas": [], "groups": [], "empty": True,
                           "notice": "舊報告"},
                created_at=now - timedelta(minutes=10),
            )
            session.add(row)
            session.flush()
            rows.append((row.id, provider, status))
    with web_client(stage) as client:
        listing = client.get(f"/api/ideation/reports?brand_id={stage.brand}").json()["reports"]
        by_id = {row["id"]: row for row in listing}
        for identity, provider, status in rows:
            assert by_id[identity]["provider"] == provider and by_id[identity]["status"] == status
            assert by_id[identity]["can_retry"] is False
            detail = client.get(f"/api/ideation/reports/{identity}")
            assert detail.status_code == 200 and detail.json()["provider"] == provider
            assert client.post(f"/api/ideation/reports/{identity}/retry").status_code == 409
    # 排程不再撿起舊 CLI 報告，也不會因此呼叫 AI。
    assert not {identity for identity, _, _ in rows} & set(
        ideation.schedule(stage.factory, stage.settings))


def test_legacy_ai_usage_rows_stay_visible_and_out_of_budget(client, ai_data):
    factory, brand_id = client.app.state.session_factory, ai_data["brand_id"]
    with factory() as session:
        before = ai.budget(session, brand_id, client.app.state.settings)
    with factory.begin() as session:
        for provider in CLI_PROVIDERS:
            for usage in ((10, 20), (None, None)):
                session.add(AIRun(
                    task="video_script", provider=provider, model="legacy-model",
                    mode="subscription", trigger="manual", brand_id=brand_id, ok=True,
                    tokens_in=usage[0], tokens_out=usage[1], duration_ms=900,
                ))
    with factory() as session:
        assert ai.budget(session, brand_id, client.app.state.settings) == before
    view = client.get(f"/api/ai/settings?brand_id={brand_id}").json()
    legacy = [run for run in view["runs"] if run["mode"] == "subscription"]
    assert {run["provider"] for run in legacy} == set(CLI_PROVIDERS)
    assert sum(run["tokens_in"] == 10 for run in legacy) == 3
    assert sum(run["tokens_in"] is None for run in legacy) == 3
    assert view["budget"]["unknown_cost_runs"] == before["unknown_cost_runs"]
    # 新紀錄一律是 API。
    ai.record(factory, "ideation", brand_id, "openai_api", "manual",
              providers.Result(model="unknown"))
    with factory() as session:
        assert session.scalar(select(AIRun).order_by(AIRun.id.desc())).mode == "api"
        after = ai.budget(session, brand_id, client.app.state.settings)
        assert after["unknown_cost_runs"] == before["unknown_cost_runs"] + 1


def test_stale_ideas_job_from_removed_regenerate_is_dropped_without_ai(stage, monkeypatch):
    rid = complete(stage, monkeypatch)
    monkeypatch.setattr(ai, "run", Mock(side_effect=AssertionError("AI forbidden")))
    with stage.factory.begin() as session:
        row = session.get(IdeationReport, rid)
        original = json.loads(json.dumps(row.data_json["ideas"]))
        row.status = "pending"
        row.data_json = {**row.data_json, "ideas_job": {
            "id": "old", "action": "regenerate", "indices": [0], "status": "pending",
            "staff_id": stage.user, "provider": "gemini_api"}}
    assert rid in ideation.schedule(stage.factory, stage.settings)
    ideation.process(stage.factory, stage.settings, rid)
    with stage.factory() as session:
        row = session.get(IdeationReport, rid)
        assert row.status == "ready" and row.data_json["ideas"] == original
        assert "ideas_job" not in row.data_json


def test_retired_draft_startup_and_route(client, ai_data, settings, monkeypatch):
    from threading import Thread

    from fastapi.testclient import TestClient

    starts = []
    original_start = Thread.start

    def start(thread):
        starts.append(thread.name)
        return original_start(thread)

    monkeypatch.setattr(Thread, "start", start)
    assert client.get(f"/api/ai/automatic-drafts/{ai_data['thread_id']}").status_code == 404
    with TestClient(create_app(settings)):
        assert not any("automatic-drafts" in name for name in starts)
    with client.app.state.session_factory() as session:
        assert not inspect(session.connection()).has_table("auto_draft_jobs")
        assert session.scalar(select(func.count()).select_from(Draft)) == 0


@pytest.mark.migration
def test_migration_cancels_pending_keeps_drafts_and_downgrade(client, ai_data, settings):
    cfg = Config(str(REPO_ROOT / "backend/alembic.ini"))
    migrate.downgrade(cfg, "0027")
    factory = client.app.state.session_factory
    response = historical_draft(client, ai_data)
    assert response.status_code == 200
    with factory.begin() as session:
        session.execute(
            text(
                "INSERT INTO auto_draft_jobs "
                "(created_at, updated_at, message_id, message_version, status, attempts) "
                "VALUES ('2026-01-01', '2026-01-01', :message, 1, 'pending', 1)"
            ),
            {"message": ai_data["message_id"]},
        )
    migrate.upgrade(cfg, "0028")
    with factory() as session:
        job = session.execute(text("SELECT status, reason FROM auto_draft_jobs")).one()
        assert job.status == "skipped" and job.reason == "manual_only"
        assert session.get(Draft, response.json()["id"]) is not None
    migrate.downgrade(cfg, "0027")
    migrate.upgrade(cfg, "head")
    with factory() as session:
        assert session.get(Draft, response.json()["id"]) is not None


def test_modules_and_settings_of_the_local_cli_are_gone():
    import importlib

    for name in ("app.services.ai.local_cli", "app.services.ai.cli_models",
                 "app.services.cli_settings", "app.services.cli_update",
                 "app.services.publish_caption", "app.schemas.local_cli"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(name)
    from app.services import idea_actions, video_scripts

    for module, names in ((idea_actions, ("request", "process")), (video_scripts, ("generate",))):
        assert not [name for name in names if hasattr(module, name)]
