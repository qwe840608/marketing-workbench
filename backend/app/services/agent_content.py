"""Agent authored content uses the web domain services and their export pipeline."""

import copy
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import HTTPException
from pydantic import ValidationError

from app.db import ensure_write
from app.models import Account, AuditLog
from app.models.agent_auth import AgentGrant
from app.models.base import utc_now
from app.models.ideation import VideoScript
from app.schemas.ideation import EditIdea, GenerateReport
from app.services import (
    agent_auth,
    agent_queries,
    content_safety,
    idea_actions,
    ideation,
    ideation_exports,
    ideation_posts,
    video_scripts,
)
from app.services.access import BrandAccess
from app.services.redact import redact, scrub

GUIDES = Path(__file__).resolve().parents[1] / "agent_guides"


def access_for(session, grant_id, *, write=False):
    if write:
        ensure_write(session)
    grant = session.get(AgentGrant, grant_id)
    staff = agent_auth.valid_grant(session, grant)
    if staff is None:
        raise HTTPException(401, "連線已失效；下一步：重新授權後再呼叫")
    if write and staff.role not in {"admin", "marketing"}:
        raise HTTPException(403, "此工具需要行銷或管理員角色；下一步：請有權限的成員操作")
    return BrandAccess(session, staff), grant


def guide(body):
    return {
        "workflow": body.workflow,
        "guide": (GUIDES / (body.workflow + ".md")).read_text(encoding="utf-8"),
    }


def kickoff(factory, settings, report_id):
    # Like the web BackgroundTask, only the committed report is passed to the worker.
    threading.Thread(
        target=ideation.process,
        args=(factory, settings, report_id),
        daemon=True,
        name="agent-ideation",
    ).start()


def check_exclusions(session, body, agent_ids, now):
    """排除的留言必須屬於所選貼文且在留言期間內，打錯的 id 直接報錯而不是默默略過。"""
    user_ids = list(body.excluded_message_ids)
    if len(set(agent_ids)) != len(agent_ids) or set(user_ids) & set(agent_ids):
        raise HTTPException(422, "同一則留言只能排除一次，且不可同時列在使用者與 Agent 排除")
    wanted = set(user_ids) | set(agent_ids)
    if not wanted:
        return []
    from app.services import ideation_evidence
    from app.services.date_ranges import comment_bounds

    start, end = comment_bounds(body.comment_range, body.comment_from, body.comment_to, now=now)
    known = {m.id for m, _, _ in session.execute(ideation_evidence.eligible(
        body.brand_id, start, end, body.post_ids))}
    if wanted - known:
        raise HTTPException(
            422, "排除的留言須屬於所選貼文且在留言期間內，請以 list_comments 確認 id"
        )
    return sorted(wanted)


def start(factory, settings, grant_id, body):
    with factory() as session:
        access, grant = access_for(session, grant_id, write=True)
        access.require_brand(body.brand_id, write=True)
        selected = [agent_queries.get_post_row(access, post_id) for post_id in body.post_ids]
        if any(
            session.get(Account, post.account_id).brand_id != body.brand_id for post in selected
        ):
            raise HTTPException(404, "找不到資料")
        now = utc_now()
        agent_ids = [item.id for item in body.agent_exclusions]
        excluded = check_exclusions(session, body, agent_ids, now)
        # Explicit post selection spans their publication dates; comment dates remain independent.
        request = GenerateReport(
            **body.model_dump(
                exclude={"brand_id", "excluded_message_ids", "agent_exclusions"}
            ),
            excluded_message_ids=excluded,
            start_at=min(post.published_at for post in selected),
            end_at=now,
        )
        result = ideation.create(
            access,
            body.brand_id,
            request,
            factory,
            settings,
            agent_source={"agent": grant.name, "grant_id": grant.id},
            agent_exclusions=[
                {"id": item.id, "reason": item.reason, "note": redact(item.note).text}
                for item in body.agent_exclusions
            ],
        )
        session.add(
            AuditLog(
                actor=f"staff:{access.staff.id}",
                brand_id=body.brand_id,
                action="ideation.report.create",
                target_type="ideation_report",
                target_id=result["id"],
                detail_json={"via": grant.name,
                             "excluded_by_user": len(body.excluded_message_ids),
                             "excluded_by_agent": len(agent_ids)},
            )
        )
        session.commit()
    kickoff(factory, settings, result["id"])
    return {"report_id": result["id"], "status": result["status"]}


def waiting_report(access, report_id):
    row = ideation.get(access, report_id)
    if row.status != "awaiting_ideas" or row.provider != "agent":
        raise HTTPException(
            409,
            "報告尚未等待 Agent 主題；下一步：重新讀取報告狀態，完成彙整後再存回；失敗時建立新報告",
        )
    started = datetime.fromisoformat(row.data_json["awaiting_ideas_at"])
    if started <= utc_now() - timedelta(hours=24):
        raise HTTPException(409, "已超過主題存回期限；下一步：建立新報告")
    return row


def evidence(access, body):
    row = waiting_report(access, body.report_id)
    data = json.loads(
        ideation.compose_prompt(ideation.brand_context(access.session, row.brand_id), row.data_json)
    )
    groups = []
    for group in row.data_json["groups"]:
        quotes = []
        for quote in group["quotes"]:
            from app.models import Message, Thread

            message = access.session.get(Message, quote["id"])
            thread = access.session.get(Thread, message.thread_id) if message else None
            contact_id = (message.contact_id or thread.contact_id) if message and thread else None
            quotes.append(
                {
                    "id": quote["id"],
                    "post_id": quote.get("post_id"),
                    "text": agent_queries.audience_text(access.session, quote["text"], contact_id),
                }
            )
        groups.append({"topic": group["topic"], "count": group["count"], "quotes": quotes})
    return {
        "report_id": row.id,
        "status": row.status,
        "groups": groups,
        # 舊報告沒有快照貼文時即時補上，讓 Agent 同樣能對照原話所回應的貼文。
        "posts": row.data_json.get("posts") or ideation_posts.quoted_posts(
            access.session, row.brand_id, row.data_json["groups"]),
        "rules": data["rules"],
        "output_format": data["output_format"],
        "save_rule": "先在對話中與使用者定案，明確要求存回後才呼叫 save_ideation_ideas。",
    }


def check_phrases(content, phrases, *, prefix=""):
    if isinstance(content, dict):
        for field, value in content.items():
            check_phrases(value, phrases, prefix=f"{prefix}.{field}" if prefix else field)
    elif isinstance(content, list):
        for index, value in enumerate(content):
            check_phrases(value, phrases, prefix=f"{prefix}[{index}]")
    elif isinstance(content, str) and content_safety.forbidden_promise(content, phrases):
        raise HTTPException(422, f"{prefix}：含品牌禁語或禁止承諾；下一步：修改此欄位後再存回")


def save_ideas(factory, settings, grant_id, body):
    with factory() as session:
        access, grant = access_for(session, grant_id, write=True)
        row = waiting_report(access, body.report_id)
        access.require_brand(row.brand_id, write=True)
        # 修正前已進入等待的報告可能沒有任何留言，同樣不接受憑空撰寫的主題。
        if not any(g["count"] for g in row.data_json.get("groups", [])):
            raise HTTPException(
                409, "此報告沒有可引用的觀眾留言，不能存回主題；下一步：改選有留言的貼文或範圍重建"
            )
        ideas = ideation.validate_ideas({"ideas": body.ideas}, row.data_json)
        phrases = ideation.brand_context(session, row.brand_id)["forbidden_phrases"]
        # Only the documented fields become durable; arbitrary keys cannot smuggle private metadata.
        fields = (
            "topic",
            "title",
            "goal",
            "hook",
            "angle",
            "keyword",
            "element",
            "visual",
            "quote_ids",
        )
        ideas = [{key: idea[key] for key in fields} for idea in ideas]
        check_phrases(ideas, phrases, prefix="ideas")
        ideas = scrub(ideas)
        row.data_json = {
            **row.data_json,
            "ideas": ideas,
            "ideas_revision": 1,
            "empty": False,
            "finished_at": utc_now().isoformat(),
        }
        row.status, row.error = "ready", None
        row.notification_status = "suppressed"
        session.add(
            AuditLog(
                actor=f"staff:{access.staff.id}",
                brand_id=row.brand_id,
                action="ideation.ideas.save",
                target_type="ideation_report",
                target_id=row.id,
                detail_json={"via": grant.name},
            )
        )
        session.commit()
    exported = ideation_exports.export_report(factory, settings, body.report_id)
    # 主題已提交；匯出失敗不讓 Agent 以為沒存到而重複寫入。
    return {
        "report_id": body.report_id,
        "status": "ready",
        "version": 1,
        "export_error": exported["error"],
    }


def edit_idea(factory, settings, grant_id, body):
    with factory() as session:
        access, grant = access_for(session, grant_id, write=True)
        row = ideation.get(access, body.report_id)
        request = EditIdea.model_validate({**body.fields, "version": body.version})
        check_phrases(
            request.model_dump(exclude={"version"}),
            ideation.brand_context(session, row.brand_id)["forbidden_phrases"],
        )
        result = idea_actions.edit(
            access, body.report_id, body.index, request, settings, factory, via=grant.name
        )
        return {
            "report_id": row.id,
            "version": result["data"]["ideas_revision"],
            "export_error": result["export_error"],
        }


def save_script(factory, settings, grant_id, body):
    with factory() as session:
        access, grant = access_for(session, grant_id)
        if access.staff.role not in {"admin", "marketing"}:
            raise HTTPException(403, "此工具需要行銷或管理員角色；下一步：請有權限的成員操作")
        report = ideation.get(access, body.report_id)
        access.require_brand(report.brand_id, write=True)
        if report.status != "ready" or body.topic_index >= len(report.data_json.get("ideas", [])):
            raise HTTPException(422, "請選擇已完成報告中的有效主題；下一步：重新讀取報告與主題索引")
        revision = report.data_json.get("ideas_revision", 1)
        idea = copy.deepcopy(report.data_json["ideas"][body.topic_index])
        quotes = [
            q
            for g in report.data_json["groups"]
            for q in g["quotes"]
            if q["id"] in idea["quote_ids"]
        ]
        brand_id = report.brand_id
        context = ideation.brand_context(session, brand_id)
    try:
        content = video_scripts.parse(json.dumps(body.content, ensure_ascii=False)).model_dump()
    except ValidationError as error:
        first = error.errors(include_input=False)[0]
        field = ".".join(str(part) for part in first["loc"]) or "duration_seconds／shots"
        reason = video_scripts.REASONS.get(first["type"], "格式不符")
        raise HTTPException(
            422, f"{field}：{reason}；下一步：依 get_brand_guide 的腳本格式修改"
        ) from None
    check_phrases(content, context["forbidden_phrases"])
    content = scrub(content)
    checked = video_scripts.review(factory, settings, brand_id, content, quotes, context)
    with factory.begin() as session:
        access, grant = access_for(session, grant_id, write=True)
        report = ideation.get(access, body.report_id)
        access.require_brand(report.brand_id, write=True)
        if (
            report.status != "ready"
            or revision != report.data_json.get("ideas_revision", 1)
            or idea != report.data_json["ideas"][body.topic_index]
            or context != ideation.brand_context(session, brand_id)
        ):
            raise HTTPException(409, "主題或品牌說明已更新；下一步：重新讀取、確認內容後再存回")
        row = VideoScript(
            brand_id=brand_id,
            report_id=body.report_id,
            topic_index=body.topic_index,
            title=content["title"],
            content_json=content,
            review_json=checked,
            provider="agent",
            model=grant.name,
        )
        session.add(row)
        actor = f"staff:{access.staff.id}"
        video_scripts.snapshot(session, row, actor)
        session.add(
            AuditLog(
                actor=actor,
                brand_id=brand_id,
                action="script.create",
                target_type="video_script",
                target_id=row.id,
                detail_json={"via": grant.name},
            )
        )
        script_id = row.id
    ideation_exports.export_script(factory, settings, script_id)
    return {
        "script_id": script_id,
        "review": {key: checked[key] for key in ("passed", "reasons", "notice")},
        "next_step": "請告知使用者檢查疑慮並由品牌覆核；可在網頁修改後重檢。"
        if not checked["passed"]
        else "已存回，仍需品牌覆核。",
    }
