"""MCP tool matrix, privacy, domain reuse and actual SDK transport on loopback."""

import asyncio
import copy
import json
import secrets
import socket
import threading
import time
from datetime import timedelta
from unittest.mock import Mock

import httpx
import pytest
import uvicorn
from agent_content_fixture import (
    fetch_comments,
    ideas_for,
    no_ai,
    script_content,
    seed_content,
    typed,
)
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import SecretStr
from sqlalchemy import func, select
from test_agent_auth import agent_client  # noqa: F401

from app.models import AuditLog, Brand, Staff, StaffBrand
from app.models.agent_auth import AgentGrant
from app.models.base import utc_now
from app.models.ideation import IdeationReport, ScriptVersion, VideoScript
from app.schemas.ideation import EditIdea
from app.services import agent_content, agent_tools, audit_retention, idea_actions, ideation, jev
from app.services.access import BrandAccess


@pytest.fixture
def content(request, monkeypatch):
    client = request.getfixturevalue("agent_client")
    factory, settings = client.app.state.session_factory, client.app.state.settings
    settings.meta_page_access_token = SecretStr("isolated-meta-secret")
    settings.comments_wake_enabled = False
    monkeypatch.setattr(agent_content, "kickoff", lambda *args: None)
    monkeypatch.setattr(jev, "ask", typed)
    monkeypatch.setattr(ideation.ai, "run", Mock(side_effect=no_ai))
    ids = seed_content(factory, client.brand_id)
    with factory.begin() as session:
        other = Brand(slug="hidden-agentquery", name="其他品牌")
        session.add(other)
        session.flush()
        ids["hidden_brand"] = other.id
        grants = {}
        for role, user in [
            ("admin", "agent-owner"),
            ("marketing", "agent-marketer"),
            ("viewer", "agent-reader"),
        ]:
            grant = AgentGrant(staff_id=client.ids[user], kind="token", name="隔離 Agent")
            session.add(grant)
            session.flush()
            grants[role] = grant.id
    client.content_ids, client.grants = ids, grants
    return client


def call(client, name, arguments=None, role="admin"):
    return agent_tools.dispatch(
        client.app.state.session_factory,
        client.app.state.settings,
        client.grants[role],
        name,
        arguments or {},
    )


def waiting(client, role="admin"):
    result = call(
        client,
        "start_ideation",
        {"brand_id": client.brand_id, "post_ids": [client.content_ids["post_id"]]},
        role,
    )
    assert not result.isError, result
    report_id = result.structuredContent["report_id"]
    fetch_comments(
        client.app.state.session_factory, client.app.state.settings, client.content_ids["post_id"]
    )
    ideation.process(client.app.state.session_factory, client.app.state.settings, report_id)
    result = call(client, "get_ideation_report", {"report_id": report_id}, role)
    assert result.structuredContent["status"] == "awaiting_ideas", result
    assert ideation.ai.run.call_count == 0
    return report_id


def ready(client, role="admin"):
    report_id = waiting(client, role)
    evidence = call(
        client, "get_ideation_evidence", {"report_id": report_id}, role
    ).structuredContent
    result = call(
        client, "save_ideation_ideas", {"report_id": report_id, "ideas": ideas_for(evidence)}, role
    )
    assert not result.isError, result
    return report_id


@pytest.mark.parametrize("role", ["admin", "marketing", "viewer"])
def test_every_tool_roles_annotations_and_audit(content, role):
    report_id = ready(content)
    saved = call(
        content,
        "save_script",
        {"report_id": report_id, "topic_index": 0, "content": script_content()},
    )
    assert not saved.isError, saved
    script_id = saved.structuredContent["script_id"]
    with content.app.state.session_factory.begin() as session:
        row = session.get(IdeationReport, report_id)
        row.status = "awaiting_ideas"
    inputs = {
        "get_server_info": {},
        "get_guide": {"workflow": "ideas"},
        "get_brand_guide": {"brand_id": content.brand_id},
        "get_dashboard": {"brand_id": content.brand_id, "days": 7},
        "list_posts": {"brand_id": content.brand_id},
        "get_post": {"post_id": content.content_ids["post_id"]},
        "list_comments": {"brand_id": content.brand_id},
        "get_popular_questions": {"brand_id": content.brand_id},
        "list_ideation_reports": {"brand_id": content.brand_id},
        "get_ideation_report": {"report_id": report_id},
        "get_script": {"script_id": script_id},
        "get_ideation_evidence": {"report_id": report_id},
        "start_ideation": {
            "brand_id": content.brand_id,
            "post_ids": [content.content_ids["post_id"]],
        },
        "save_ideation_ideas": {
            "report_id": report_id,
            "ideas": ideas_for(
                call(content, "get_ideation_evidence", {"report_id": report_id}).structuredContent
            ),
        },
        "edit_idea": {
            "report_id": report_id,
            "index": 0,
            "version": 1,
            "fields": {k: "修改流程" for k in ("title", "hook", "angle", "keyword", "visual")},
        },
        "save_script": {"report_id": report_id, "topic_index": 0, "content": script_content()},
    }
    # Publishing has its own exhaustive role/state fixtures in test_agent_publish.
    assert set(inputs) == set(agent_tools.SPECS) - set(agent_tools.PUBLISH_SPECS)
    for tool in (tool for tool in agent_tools.list_tools() if tool.name in inputs):
        with content.app.state.session_factory() as session:
            before = session.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action.in_(["agent.tool.read", "agent.tool.write"])
                )
            )
        result = call(content, tool.name, inputs[tool.name], role)
        write = agent_tools.SPECS[tool.name][1]
        if role == "viewer" and write:
            assert result.isError and "功能權限" in result.content[0].text
        else:
            assert not result.isError, (tool.name, result)
        assert tool.annotations.readOnlyHint is not write
        assert "下一步" in tool.description
        with content.app.state.session_factory() as session:
            audits = list(
                session.scalars(
                    select(AuditLog)
                    .where(AuditLog.action.in_(["agent.tool.read", "agent.tool.write"]))
                    .order_by(AuditLog.id)
                )
            )
            assert len(audits) == before + 1
            audit = audits[-1]
            assert audit.actor.startswith("staff:")
            assert set(audit.detail_json) == {"tool", "connection_name", "grant_id", "result"}
            assert audit.detail_json["grant_id"] == content.grants[role]


@pytest.mark.parametrize("name", list(agent_tools.SPECS))
def test_every_tool_validation_does_not_echo_input(content, name):
    secret = secrets.token_urlsafe(32)
    result = call(content, name, {secret: secret})
    assert result.isError
    assert secret not in result.content[0].text
    assert "下一步" in result.content[0].text


@pytest.mark.parametrize(
    "name",
    [
        "get_brand_guide",
        "get_dashboard",
        "list_posts",
        "list_comments",
        "get_popular_questions",
        "list_ideation_reports",
        "start_ideation",
    ],
)
def test_brand_tools_hide_other_brands(content, name):
    args = {"brand_id": content.content_ids["hidden_brand"]}
    if name == "start_ideation":
        args["post_ids"] = [content.content_ids["post_id"]]
    result = call(content, name, args, "marketing")
    assert result.isError and "找不到" in result.content[0].text


def test_resource_tools_hide_other_brands_and_deleted(content):
    report_id = ready(content)
    saved = call(
        content,
        "save_script",
        {"report_id": report_id, "topic_index": 0, "content": script_content()},
    )
    script_id = saved.structuredContent["script_id"]
    with content.app.state.session_factory.begin() as session:
        session.execute(
            __import__("sqlalchemy")
            .delete(StaffBrand)
            .where(StaffBrand.staff_id == content.ids["agent-marketer"])
        )
    cases = [
        ("get_post", {"post_id": content.content_ids["post_id"]}),
        ("get_ideation_report", {"report_id": report_id}),
        ("get_ideation_evidence", {"report_id": report_id}),
        ("get_script", {"script_id": script_id}),
        ("save_script", {"report_id": report_id, "topic_index": 0, "content": script_content()}),
        (
            "edit_idea",
            {
                "report_id": report_id,
                "index": 0,
                "version": 1,
                "fields": {k: "流程" for k in ("title", "hook", "angle", "visual", "keyword")},
            },
        ),
        ("save_ideation_ideas", {"report_id": report_id, "ideas": []}),
    ]
    for name, args in cases:
        result = call(content, name, args, "marketing")
        assert result.isError and "找不到" in result.content[0].text, result
    with content.app.state.session_factory.begin() as session:
        session.get(IdeationReport, report_id).status = "deleted"
    assert call(content, "get_ideation_report", {"report_id": report_id}).isError
    assert call(content, "get_script", {"script_id": script_id}).isError
    assert (
        call(content, "list_ideation_reports", {"brand_id": content.brand_id}).structuredContent[
            "items"
        ]
        == []
    )


def test_privacy_pagination_iso_dates_and_defaults(content):
    args = {"brand_id": content.brand_id, "limit": 2}
    first = call(content, "list_comments", args).structuredContent
    assert first["next_offset"] == 2
    assert first["items"][0]["author"] == first["items"][1]["author"] == "觀眾A"
    second = call(content, "list_comments", {**args, "offset": 2}).structuredContent
    assert second["next_offset"] is None and len(second["items"]) == 1
    assert first["items"][0]["sent_at"].endswith("+08:00")
    rendered = json.dumps(first, ensure_ascii=False)
    for sensitive in (
        "測試觀眾名字",
        "fake-platform-id",
        "fake.viewer",
        "0912345678",
        "audience@example.test",
    ):
        assert sensitive not in rendered
    assert "REDACTED_PHONE" in rendered and "REDACTED_EMAIL" in rendered
    dates = {"since": (utc_now() - timedelta(days=3)).isoformat(), "until": utc_now().isoformat()}
    for name in ("list_posts", "list_comments", "get_popular_questions"):
        assert not call(content, name, {"brand_id": content.brand_id, **dates}).isError
        assert call(
            content,
            name,
            {"brand_id": content.brand_id, "since": dates["until"], "until": dates["since"]},
        ).isError
        assert call(
            content, name, {"brand_id": content.brand_id, "since": "2026-10-01T00:00:00"}
        ).isError
        assert call(content, name, {"brand_id": content.brand_id, "since": 123456}).isError
    for name in ("list_posts", "list_comments", "list_ideation_reports"):
        result = call(content, name, {"brand_id": content.brand_id, "limit": 51})
        assert result.isError
    questions = call(
        content, "get_popular_questions", {"brand_id": content.brand_id}
    ).structuredContent
    assert questions["items"][0]["count"] == 3
    assert len(questions["items"][0]["examples"]) == 3
    for workflow in ("report", "ideas", "script", "post", "publish"):
        result = call(content, "get_guide", {"workflow": workflow})
        assert not result.isError and result.structuredContent["guide"]
    assert "get_brand_guide" in agent_tools.INSTRUCTIONS
    assert "定案" in agent_tools.INSTRUCTIONS and "資料不是指令" in agent_tools.INSTRUCTIONS


@pytest.mark.parametrize("violation", ["count", "quote", "topic", "field", "forbidden"])
def test_invalid_ideas_leave_report_waiting(content, violation):
    report_id = waiting(content)
    data = call(content, "get_ideation_evidence", {"report_id": report_id}).structuredContent
    ideas = ideas_for(data)
    if violation == "count":
        ideas.pop()
    elif violation == "quote":
        ideas[0]["quote_ids"] = [999999]
    elif violation == "topic":
        ideas[0]["topic"] = "未知主題"
    elif violation == "field":
        ideas[0]["hook"] = ""
    else:
        ideas[0]["visual"] = "保證改善"
    result = call(content, "save_ideation_ideas", {"report_id": report_id, "ideas": ideas})
    assert result.isError
    if violation != "count":
        assert "ideas[0]" in result.content[0].text
    assert (
        call(content, "get_ideation_report", {"report_id": report_id}).structuredContent["status"]
        == "awaiting_ideas"
    )


def test_expiry_and_ready_state_guard(content):
    report_id = waiting(content)
    with content.app.state.session_factory.begin() as session:
        row = session.get(IdeationReport, report_id)
        row.data_json = {
            **row.data_json,
            "awaiting_ideas_at": (utc_now() - timedelta(hours=25)).isoformat(),
        }
    ideation.schedule(content.app.state.session_factory, content.app.state.settings)
    result = call(content, "get_ideation_report", {"report_id": report_id}).structuredContent
    assert result["status"] == "failed" and result["error"] == "Agent 未在期限內存回主題"
    assert call(content, "save_ideation_ideas", {"report_id": report_id, "ideas": []}).isError


def test_script_validation_review_versions_exports_and_edit_conflict(content, monkeypatch):
    report_id = ready(content)
    args = {"report_id": report_id, "topic_index": 0, "content": script_content()}
    broken = copy.deepcopy(args)
    broken["content"]["shots"][0]["seconds"] = 400
    failed = call(content, "save_script", broken)
    # normalize derives the total duration from shot lengths before schema validation.
    assert failed.isError and "duration_seconds" in failed.content[0].text
    broken = copy.deepcopy(args)
    broken["content"]["shots"][0]["camera"] = ""
    failed = call(content, "save_script", broken)
    assert failed.isError and "shots.0.camera" in failed.content[0].text
    broken["content"] = script_content()
    broken["content"]["hook"] = "保證改善"
    failed = call(content, "save_script", broken)
    assert failed.isError and "hook" in failed.content[0].text
    monkeypatch.setattr(jev, "ask", lambda *args: jev.Result(None, 0, "unavailable"))
    saved = call(content, "save_script", args)
    assert not saved.isError
    assert not saved.structuredContent["review"]["passed"]
    assert "jev" in saved.structuredContent["review"]["reasons"][0]
    second = call(content, "save_script", args)
    assert (
        not second.isError
        and second.structuredContent["script_id"] != saved.structuredContent["script_id"]
    )
    with content.app.state.session_factory() as session:
        for sid in (saved.structuredContent["script_id"], second.structuredContent["script_id"]):
            row = session.get(VideoScript, sid)
            assert row.provider == "agent" and row.model == "隔離 Agent"
            assert (
                session.scalar(
                    select(func.count(ScriptVersion.id)).where(ScriptVersion.script_id == sid)
                )
                == 1
            )
            assert row.export_json["md"] and row.export_json["docx"]
            from pathlib import Path

            assert Path(row.export_json["md"]).is_relative_to(
                content.app.state.settings.export_root
            )
            assert Path(row.export_json["docx"]).is_file()
    fields = {k: "修訂流程" for k in ("title", "hook", "angle", "keyword", "visual")}
    edited = call(
        content, "edit_idea", {"report_id": report_id, "index": 0, "version": 1, "fields": fields}
    )
    assert not edited.isError and edited.structuredContent["version"] == 2
    conflict = call(
        content, "edit_idea", {"report_id": report_id, "index": 0, "version": 1, "fields": fields}
    )
    assert conflict.isError and "重新" in conflict.content[0].text
    # The web path preserves the existing revision/history semantics on Agent reports.
    with content.app.state.session_factory() as session:
        access = BrandAccess(session, session.get(Staff, content.ids["agent-owner"]))
        result = idea_actions.edit(
            access,
            report_id,
            0,
            EditIdea(version=2, **fields),
            content.app.state.settings,
            content.app.state.session_factory,
        )
        assert result["data"]["ideas_revision"] == 3
        assert len(result["data"]["ideas_history"]["0"]) == 2


def test_read_audit_retention_and_response_bound(content):
    call(content, "get_server_info")
    with content.app.state.session_factory.begin() as session:
        row = session.scalars(select(AuditLog).where(AuditLog.action == "agent.tool.read")).first()
        row.at = utc_now() - timedelta(days=31)
        session.add(
            AuditLog(
                actor="staff:1",
                action="script.create",
                target_type="video_script",
                at=utc_now() - timedelta(days=31),
                detail_json={},
            )
        )
    assert audit_retention.prune(content.app.state.session_factory) == 1
    value = agent_tools.bounded(
        {"items": [{"id": i, "text": "字" * 20000} for i in range(50)], "next_offset": None},
        offset=20,
    )
    assert value["truncated"] and value["next_offset"] == 20 + len(value["items"])
    assert len(json.dumps(value, ensure_ascii=False, separators=(",", ":"))) <= agent_tools.MAX_TEXT
    single = agent_tools.bounded({"groups": [{"quotes": [{"id": 1, "text": "字" * 100000}]}]})
    assert single["groups"][0]["quotes"][0]["id"] == 1 and single["truncated"]
    questions = agent_tools.bounded(
        {
            "items": [{"intent": str(index), "text": "字" * 30000} for index in range(3)],
            "next_offset": None,
        }
    )
    assert len(questions["items"]) == 3 and questions["next_offset"] is None
    assert questions["truncated"]


def test_agent_ready_report_uses_existing_web_edit_and_draft(content, monkeypatch):
    from app.services import publish

    report_id = ready(content)
    # 網頁編輯與建立草稿都不呼叫任何 AI。
    monkeypatch.setattr(ideation.ai, "run", lambda *a, **kw: pytest.fail("must not call AI"))
    prefix = f"/api/ideation/reports/{report_id}/ideas"
    fields = {key: "網頁修訂流程" for key in ("title", "hook", "angle", "keyword", "visual")}
    response = content.put(prefix + "/0", json={"version": 1, **fields})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["ideas_revision"] == 2
    result = content.get(f"/api/ideation/reports/{report_id}").json()
    assert result["status"] == "ready" and len(result["data"]["ideas"]) == 15
    assert result["source"]["agent"] == "隔離 Agent"
    draft = content.post(
        "/api/publish/ideation-draft", json={"report_id": report_id, "idea_index": 0}
    )
    assert draft.status_code == 200, draft.text
    post = draft.json()["post"]
    assert draft.json()["created"] and post["status"] == "draft"
    assert post["caption"] == publish.idea_caption(result["data"]["ideas"][0])
    assert "網頁修訂流程" in post["caption"] and "caption_job" not in post


def test_mixed_brand_selection_and_extra_idea_keys_do_not_leak(content):
    mixed = call(
        content,
        "start_ideation",
        {
            "brand_id": content.content_ids["hidden_brand"],
            "post_ids": [content.content_ids["post_id"]],
        },
    )
    assert mixed.isError and "找不到" in mixed.content[0].text
    report_id = waiting(content)
    evidence = call(content, "get_ideation_evidence", {"report_id": report_id}).structuredContent
    ideas = ideas_for(evidence)
    secret = secrets.token_urlsafe(40)
    ideas[0][secret] = "保證改善"
    saved = call(content, "save_ideation_ideas", {"report_id": report_id, "ideas": ideas})
    assert not saved.isError and secret not in saved.content[0].text
    result = call(content, "get_ideation_report", {"report_id": report_id})
    assert secret not in result.content[0].text


def test_ideation_evidence_carries_full_redacted_post_caption(content):
    from app.models import Post

    caption = "長內文開頭 " + "說明" * 40 + " 聯絡 0912345678"
    with content.app.state.session_factory.begin() as session:
        session.get(Post, content.content_ids["post_id"]).caption = caption
    report_id = waiting(content)
    evidence = call(content, "get_ideation_evidence", {"report_id": report_id}).structuredContent
    quoted = {q["post_id"] for g in evidence["groups"] for q in g["quotes"]}
    assert quoted == {content.content_ids["post_id"]}
    [post] = evidence["posts"]
    assert post["id"] == content.content_ids["post_id"]
    # 全文（遠超過清單的 30 字）送進發想，但個資仍遮蔽。
    assert post["caption"].startswith("長內文開頭 " + "說明" * 40)
    assert "0912345678" not in post["caption"]
    with content.app.state.session_factory() as session:
        stored = session.get(IdeationReport, report_id).data_json["posts"]
    assert [(x["id"], x["caption"]) for x in stored] == [(post["id"], post["caption"])]


def test_start_ideation_user_and_agent_exclusions(content):
    from app.models import AuditLog

    factory, settings = content.app.state.session_factory, content.app.state.settings
    post_id = content.content_ids["post_id"]
    waiting(content)  # 先同步一次，留言才會入庫可供 list_comments 取得 id
    listed = call(content, "list_comments", {"brand_id": content.brand_id, "post_id": post_id})
    ids = [item["id"] for item in listed.structuredContent["items"]]
    assert len(ids) >= 2, ids
    base = {"brand_id": content.brand_id, "post_ids": [post_id]}
    # 打錯或不屬於所選貼文的 id、同一則重複排除、不在清單內的理由都拒絕，不會默默略過。
    for bad in (
        {"excluded_message_ids": [999999]},
        {"agent_exclusions": [{"id": 999999, "reason": "spam"}]},
        {"excluded_message_ids": [ids[0]], "agent_exclusions": [{"id": ids[0], "reason": "spam"}]},
        {"agent_exclusions": [{"id": ids[0], "reason": "negative"}]},
    ):
        assert call(content, "start_ideation", {**base, **bad}).isError, bad
    result = call(content, "start_ideation", {
        **base, "excluded_message_ids": [ids[0]],
        "agent_exclusions": [{"id": ids[1], "reason": "spam", "note": "聯絡 0912345678 買粉"}],
    })
    assert not result.isError, result
    report_id = result.structuredContent["report_id"]
    # 剛同步過，不會再排入抓取，直接彙整。
    ideation.process(factory, settings, report_id)
    report = call(content, "get_ideation_report", {"report_id": report_id}).structuredContent
    assert report["status"] == "awaiting_ideas", report
    assert report["exclusions"]["by_user"] == 1
    [agent] = report["exclusions"]["by_agent"]
    assert agent["id"] == ids[1] and agent["reason"] == "spam" and "廣告" in agent["reason_label"]
    assert "0912345678" not in agent["note"]
    evidence = call(content, "get_ideation_evidence", {"report_id": report_id}).structuredContent
    quoted = {q["id"] for g in evidence["groups"] for q in g["quotes"]}
    assert not quoted & {ids[0], ids[1]}
    with factory() as session:
        stored = session.get(IdeationReport, report_id).data_json
        assert stored["excluded_message_ids"] == sorted(ids[:2])
        audit = session.scalars(select(AuditLog).where(
            AuditLog.action == "ideation.report.create", AuditLog.target_id == report_id)).one()
        assert audit.detail_json["excluded_by_user"] == 1
        assert audit.detail_json["excluded_by_agent"] == 1


def test_agent_report_without_comments_ends_without_ideas(content):
    factory, settings = content.app.state.session_factory, content.app.state.settings
    post_id = content.content_ids["post_id"]
    legacy = waiting(content)
    evidence = call(content, "get_ideation_evidence", {"report_id": legacy})
    ideas = ideas_for(evidence.structuredContent)
    listed = call(content, "list_comments", {"brand_id": content.brand_id, "post_id": post_id,
                                             "limit": 50})
    ids = [item["id"] for item in listed.structuredContent["items"]]
    # 全部留言都被排除＝沒有可引用的觀眾聲音：與 API 模型一樣直接結束，不進入等待撰寫。
    result = call(content, "start_ideation", {"brand_id": content.brand_id, "post_ids": [post_id],
                                              "excluded_message_ids": ids})
    assert not result.isError, result
    report_id = result.structuredContent["report_id"]
    ideation.process(factory, settings, report_id)
    report = call(content, "get_ideation_report", {"report_id": report_id}).structuredContent
    assert report["status"] == "ready" and report["ideas"] == [], report
    with factory() as session:
        row = session.get(IdeationReport, report_id)
        assert row.data_json["empty"] is True
        assert row.notification_status == "suppressed"
    assert call(content, "get_ideation_evidence", {"report_id": report_id}).isError
    # 修正前已在等待中的空報告也不接受憑空撰寫的主題。
    with factory.begin() as session:
        row = session.get(IdeationReport, legacy)
        row.data_json = {**row.data_json,
                         "groups": [{**g, "count": 0} for g in row.data_json["groups"]]}
    saved = call(content, "save_ideation_ideas", {"report_id": legacy, "ideas": ideas})
    assert saved.isError and "沒有可引用" in saved.content[0].text
    assert ideation.ai.run.call_count == 0


def test_post_report_pages_snapshot_cap_and_default_comment_periods(content):
    from app.models import Message, MetricSnapshot, Post

    now = utc_now()
    with content.app.state.session_factory.begin() as session:
        for index in range(51):
            session.add(
                Post(
                    account_id=content.content_ids["account_id"],
                    external_id=f"page-post-{index}",
                    media_type="IMAGE",
                    published_at=now - timedelta(hours=2),
                    caption="聯絡 0912345678 viewer@example.test",
                )
            )
        for _index in range(21):
            session.add(
                IdeationReport(
                    brand_id=content.brand_id,
                    meeting_at=now,
                    start_at=now - timedelta(days=7),
                    end_at=now,
                    status="ready",
                    provider="fixture",
                    trigger="manual",
                    data_json={"ideas": []},
                )
            )
        session.add(
            IdeationReport(
                brand_id=content.brand_id,
                meeting_at=now,
                start_at=now,
                end_at=now,
                status="deleted",
                provider="fixture",
                trigger="manual",
                data_json={},
            )
        )
        for index in range(31):
            session.add(
                MetricSnapshot(
                    post_id=content.content_ids["post_id"],
                    captured_at=now + timedelta(seconds=index),
                    reach=index,
                )
            )
        for days in (31, 91):
            session.add(
                Message(
                    thread_id=content.content_ids["thread_id"],
                    direction="in",
                    author_type="fan",
                    external_id=f"old-comment-{days}",
                    text="較早的流程問題",
                    sent_at=now - timedelta(days=days),
                )
            )
    args = {"brand_id": content.brand_id, "platform": "instagram", "limit": 50}
    first = call(content, "list_posts", args).structuredContent
    assert len(first["items"]) == 50 and first["next_offset"] == 50
    second = call(content, "list_posts", {**args, "offset": 50}).structuredContent
    assert len(second["items"]) == 2 and second["next_offset"] is None
    assert {row["id"] for row in first["items"]}.isdisjoint(row["id"] for row in second["items"])
    assert "0912345678" not in json.dumps(first) and "viewer@example.test" not in json.dumps(first)
    detail = call(
        content, "get_post", {"post_id": content.content_ids["post_id"]}
    ).structuredContent
    assert len(detail["snapshots"]) == 30
    assert detail["snapshots"][0]["reach"] == 30 and detail["snapshots"][-1]["reach"] == 1
    assert all(row["captured_at"].endswith("+08:00") for row in detail["snapshots"])
    args = {"brand_id": content.brand_id}
    first = call(content, "list_ideation_reports", args).structuredContent
    assert len(first["items"]) == 20 and first["next_offset"] == 20
    second = call(content, "list_ideation_reports", {**args, "offset": 20}).structuredContent
    assert len(second["items"]) == 1 and second["next_offset"] is None
    comments = call(content, "list_comments", args).structuredContent
    assert len(comments["items"]) == 4
    questions = call(content, "get_popular_questions", args).structuredContent
    assert sum(group["count"] for group in questions["items"]) == 3


def test_posts_return_full_caption_brand_url_and_image(content):
    import base64

    from app.models import Post, PostThumbnail

    post_id = content.content_ids["post_id"]
    caption = "開頭 " + "完整內文" * 80 + " 聯絡 0912345678 結尾問句？"
    jpeg = b"\xff\xd8\xff\xe0fake-jpeg-bytes"
    with content.app.state.session_factory.begin() as session:
        post = session.get(Post, post_id)
        post.caption = caption
        post.permalink = "https://www.threads.com/@brandhandle/post/abc"
        session.add(
            PostThumbnail(
                post_id=post_id, status="ready", mime="image/jpeg", width=480, height=600,
                digest="d" * 64, data=jpeg,
            )
        )
    listed = call(content, "list_posts", {"brand_id": content.brand_id}).structuredContent
    [item] = [row for row in listed["items"] if row["id"] == post_id]
    # 清單也給完整文案（不再只有前 200 字），個資照樣遮蔽。
    assert item["caption"].endswith("結尾問句？") and "0912345678" not in item["caption"]
    assert item["url"] == "https://www.threads.com/@brandhandle/post/abc"
    assert item["has_image"] is True and item["media_type"]
    result = call(content, "get_post", {"post_id": post_id})
    assert not result.isError
    assert result.structuredContent["has_image"] is True
    [text, image] = result.content
    assert text.type == "text" and image.type == "image"
    assert image.mimeType == "image/jpeg" and base64.b64decode(image.data) == jpeg
    assert "fake-jpeg" not in text.text
    for role in ("marketing", "viewer"):
        assert call(content, "get_post", {"post_id": post_id}, role).content[1].type == "image"
    with content.app.state.session_factory.begin() as session:
        session.get(PostThumbnail, session.scalar(
            select(PostThumbnail.id).where(PostThumbnail.post_id == post_id)
        )).status = "unavailable"
    result = call(content, "get_post", {"post_id": post_id})
    assert [part.type for part in result.content] == ["text"]
    assert result.structuredContent["has_image"] is False


def test_script_rechecks_grant_after_jev_review(content, monkeypatch):
    report_id = ready(content)
    original = agent_content.video_scripts.review

    def review(*args):
        result = original(*args)
        with content.app.state.session_factory.begin() as session:
            session.get(Staff, content.ids["agent-owner"]).role = "viewer"
        return result

    monkeypatch.setattr(agent_content.video_scripts, "review", review)
    result = call(
        content,
        "save_script",
        {"report_id": report_id, "topic_index": 0, "content": script_content()},
    )
    assert result.isError and "功能權限" in result.content[0].text
    with content.app.state.session_factory() as session:
        assert session.scalar(select(func.count(VideoScript.id))) == 0


def test_sdk_full_agent_flow_on_random_loopback_port(content):
    token = content.post("/api/agent/connections", json={"name": "隔離 SDK 內容"}).json()["token"]
    bound = socket.socket()
    bound.bind(("127.0.0.1", 0))
    port = bound.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(content.app, log_level="critical", lifespan="on"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [bound]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started

        async def exercise():
            async with httpx.AsyncClient(headers={"Authorization": "Bearer " + token}) as http:
                async with streamable_http_client(
                    f"http://127.0.0.1:{port}/mcp", http_client=http
                ) as (read, write, _):
                    async with ClientSession(read, write) as sdk:
                        init = await sdk.initialize()
                        assert init.instructions == agent_tools.INSTRUCTIONS
                        tools = await sdk.list_tools()
                        assert {tool.name for tool in tools.tools} == set(agent_tools.SPECS)
                        brand = await sdk.call_tool(
                            "get_brand_guide", {"brand_id": content.brand_id}
                        )
                        assert not brand.isError
                        posts = await sdk.call_tool("list_posts", {"brand_id": content.brand_id})
                        post_id = posts.structuredContent["items"][0]["id"]
                        report = await sdk.call_tool(
                            "start_ideation", {"brand_id": content.brand_id, "post_ids": [post_id]}
                        )
                        report_id = report.structuredContent["report_id"]
                        fetch_comments(
                            content.app.state.session_factory, content.app.state.settings, post_id
                        )
                        ideation.process(
                            content.app.state.session_factory, content.app.state.settings, report_id
                        )
                        progress = await sdk.call_tool(
                            "get_ideation_report", {"report_id": report_id}
                        )
                        assert progress.structuredContent["status"] == "awaiting_ideas"
                        evidence = await sdk.call_tool(
                            "get_ideation_evidence", {"report_id": report_id}
                        )
                        saved = await sdk.call_tool(
                            "save_ideation_ideas",
                            {
                                "report_id": report_id,
                                "ideas": ideas_for(evidence.structuredContent),
                            },
                        )
                        assert not saved.isError
                        script = await sdk.call_tool(
                            "save_script",
                            {"report_id": report_id, "topic_index": 0, "content": script_content()},
                        )
                        assert not script.isError and script.structuredContent["review"]["passed"]
                        assert ideation.ai.run.call_count == 0

        asyncio.run(exercise())
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        bound.close()
        assert not thread.is_alive()


@pytest.mark.parametrize(
    ("display_name", "external_id", "text", "expected"),
    [
        # 一兩個字的名稱不替換，避免把「小美好」改成「[觀眾]好」。
        ("小美", "Jo", "小美好可愛，Jo 說 John 很好", "小美好可愛，Jo 說 John 很好"),
        ("陳小明", "Joe", "陳小明你好，Joe 和 Joey 都來了", "[觀眾]你好，[觀眾] 和 Joey 都來了"),
    ],
)
def test_audience_text_skips_short_names_and_respects_word_edges(
    display_name, external_id, text, expected
):
    from types import SimpleNamespace

    from app.services import agent_queries

    contact = SimpleNamespace(display_name=display_name, external_id=external_id)
    session = SimpleNamespace(get=lambda model, identity: contact)
    assert agent_queries.audience_text(session, text, 1) == expected
