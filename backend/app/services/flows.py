"""發文流程：方塊與連線決定何時準備草稿、核准後怎麼排；送出一律交給既有發佈與排程器。

流程本身不呼叫任何平台 API。核准時把每個「發佈」方塊轉成一篇已排程的 PublishPost，
之後的發送、重試、錯過與通知都沿用 publish.py 的規則。
"""

import secrets
import shutil
from copy import deepcopy
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.db import ensure_write
from app.logging_config import log_failure
from app.models import (
    AuditLog,
    NotificationDelivery,
    PublishFlow,
    PublishFlowRun,
    PublishMedia,
    PublishPost,
)
from app.models.base import utc_now
from app.models.ideation import IdeationReport
from app.schemas.flows import (
    ApprovalConfig,
    DelayConfig,
    DraftConfig,
    NotifyConfig,
    PublishConfig,
    TriggerConfig,
)
from app.schemas.publish import PublishAction
from app.services import notify, publish, publish_rules, roles
from app.services.publish_media import path_for, remove_files
from app.services.redact import redact

TAIPEI = ZoneInfo("Asia/Taipei")
CONFIGS = {
    "trigger": TriggerConfig,
    "draft": DraftConfig,
    "approval": ApprovalConfig,
    "publish": PublishConfig,
    "delay": DelayConfig,
    "notify": NotifyConfig,
}
# 觸發時間過了五分鐘才被看到（例如電腦關機）就不補跑，與排程貼文「已錯過」一致。
MISSED_AFTER = timedelta(minutes=5)
# 核准後第一篇最早兩分鐘後送出：publish.prepare 要求排程在一分鐘之後，多留一分鐘緩衝。
MIN_LEAD = timedelta(minutes=2)
# 同一次執行的貼文至少相隔一分鐘，避免同時大量呼叫平台 API。
MIN_GAP = timedelta(minutes=1)
MAX_SPAN = timedelta(days=30)
UNITS = {"minutes": 60, "hours": 3600, "days": 86400}
POST_DONE = {"done", "partial", "failed", "missed", "cancelled"}
RUN_OPEN = {"running", "awaiting_approval", "scheduled"}
STATUS_NAMES = {
    "done": "發佈成功",
    "partial": "部分成功",
    "failed": "發佈失敗",
    "missed": "已錯過",
    "cancelled": "已取消",
}


# ── 流程圖驗證 ──────────────────────────────────────────────


def parse_config(node):
    return CONFIGS[node["type"]].model_validate(node.get("config") or {})


def validate(graph):
    """回傳 {ok, errors, nodes: {id: [錯誤]}, order}；order 是從觸發開始的一直線。"""
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    errors, per_node = [], {node["id"]: [] for node in nodes}
    by_id = {node["id"]: node for node in nodes}
    if len(by_id) != len(nodes):
        errors.append("方塊代號重複")
    for node in nodes:
        try:
            config = parse_config(node)
        except ValidationError:
            per_node[node["id"]].append("設定格式不正確")
            continue
        if node["type"] == "trigger":
            if config.mode == "weekly" and not config.weekdays:
                per_node[node["id"]].append("請至少選一天")
            if config.mode == "once" and not config.date:
                per_node[node["id"]].append("請選擇日期")
        if node["type"] == "draft" and config.source == "template" and not config.caption.strip():
            per_node[node["id"]].append("請輸入範本文案")
        if node["type"] == "draft" and config.source == "post" and not config.post_id:
            per_node[node["id"]].append("請選擇草稿")
        if node["type"] == "publish" and not config.platforms:
            per_node[node["id"]].append("請至少選一個平台")
    outgoing, incoming = {}, {}
    for edge in edges:
        if edge["source"] not in by_id or edge["target"] not in by_id:
            errors.append("連線指向不存在的方塊")
            continue
        if edge["source"] == edge["target"]:
            per_node[edge["source"]].append("方塊不能連到自己")
            continue
        outgoing.setdefault(edge["source"], []).append(edge["target"])
        incoming.setdefault(edge["target"], []).append(edge["source"])
    for identity in by_id:
        if len(outgoing.get(identity, [])) > 1:
            per_node[identity].append("這一版每個方塊只能接一條出去的線")
        if len(incoming.get(identity, [])) > 1:
            per_node[identity].append("這一版每個方塊只能接一條進來的線")
    triggers = [node for node in nodes if node["type"] == "trigger"]
    order = []
    if len(triggers) != 1:
        errors.append("流程需要剛好一個「時間觸發」")
    else:
        trigger = triggers[0]
        if incoming.get(trigger["id"]):
            per_node[trigger["id"]].append("時間觸發必須在最前面")
        current, seen = trigger["id"], set()
        while current and current not in seen:
            seen.add(current)
            order.append(by_id[current])
            following = outgoing.get(current, [])
            current = following[0] if len(following) == 1 else None
        if current in seen:
            errors.append("流程不能有迴圈")
        for identity in by_id:
            if identity not in seen:
                per_node[identity].append("沒有接到流程上")
    kinds = [node["type"] for node in order]
    drafts = [i for i, kind in enumerate(kinds) if kind == "draft"]
    approvals = [i for i, kind in enumerate(kinds) if kind == "approval"]
    publishes = [i for i, kind in enumerate(kinds) if kind == "publish"]
    if sum(node["type"] == "draft" for node in nodes) != 1:
        errors.append("流程需要剛好一個「建立草稿」")
    if sum(node["type"] == "approval" for node in nodes) != 1:
        errors.append("流程需要剛好一個「等待核准」")
    if not any(node["type"] == "publish" for node in nodes):
        errors.append("流程至少需要一個「發佈」")
    if drafts and approvals and drafts[0] > approvals[0]:
        per_node[order[drafts[0]]["id"]].append("建立草稿必須在等待核准之前")
    for index in publishes:
        if not approvals or index < approvals[0]:
            per_node[order[index]["id"]].append("發佈之前必須先經過等待核准")
    ok = not errors and not any(per_node.values())
    return {
        "ok": ok,
        "errors": errors,
        "nodes": {key: value for key, value in per_node.items() if value},
        "order": [node["id"] for node in order],
    }


def chain(graph):
    by_id = {node["id"]: node for node in graph.get("nodes", [])}
    return [by_id[identity] for identity in validate(graph)["order"]]


def after(graph, identity):
    order = [node["id"] for node in chain(graph)]
    index = order.index(identity)
    return order[index + 1] if index + 1 < len(order) else None


def node_of(graph, identity):
    return next(node for node in graph["nodes"] if node["id"] == identity)


def publish_platforms(graph):
    platforms = []
    for node in chain(graph):
        if node["type"] == "publish":
            for platform in parse_config(node).platforms:
                if platform not in platforms:
                    platforms.append(platform)
    return platforms


# ── 時間計算（台北時間）────────────────────────────────────


def at_clock(day, clock):
    hour, minute = (int(part) for part in clock.split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TAIPEI)


def next_trigger(config, moment):
    """moment 之後（不含）的下一次觸發；沒有下一次回 None。"""
    local = moment.astimezone(TAIPEI)
    if config.mode == "once":
        when = at_clock(config.date, config.time) if config.date else None
        return when.astimezone(moment.tzinfo) if when and when > moment else None
    for offset in range(8):
        day = local.date() + timedelta(days=offset)
        if config.mode == "weekly" and day.weekday() not in config.weekdays:
            continue
        when = at_clock(day, config.time)
        if when > moment:
            return when.astimezone(moment.tzinfo)
    return None


def apply_delay(config, moment):
    if config.at:
        local = moment.astimezone(TAIPEI)
        when = at_clock(local.date(), config.at)
        if when <= moment:
            when = at_clock(local.date() + timedelta(days=1), config.at)
        return when.astimezone(moment.tzinfo)
    return moment + timedelta(seconds=config.amount * UNITS[config.unit])


def plan(graph, approval_id, base):
    """核准時間為 base 時，每個發佈方塊的排程時間。"""
    items, cursor, last = [], base, None
    identity = after(graph, approval_id)
    while identity:
        node = node_of(graph, identity)
        if node["type"] == "delay":
            cursor = apply_delay(parse_config(node), cursor)
        elif node["type"] == "publish":
            when = max(cursor, base + MIN_LEAD, (last + MIN_GAP) if last else base)
            items.append({"node": identity, "platforms": parse_config(node).platforms, "at": when})
            last = when
        identity = after(graph, identity)
    return items


# ── 檢視 ─────────────────────────────────────────────────


def flow_view(session, flow):
    last = session.scalar(
        select(PublishFlowRun)
        .where(PublishFlowRun.flow_id == flow.id)
        .order_by(PublishFlowRun.id.desc())
        .limit(1)
    )
    return {
        "id": flow.id,
        "brand_id": flow.brand_id,
        "name": flow.name,
        "enabled": flow.enabled,
        "graph": flow.graph_json,
        "validation": validate(flow.graph_json),
        "next_run_at": flow.next_run_at,
        "last_run": (
            {"id": last.id, "status": last.status, "trigger_at": last.trigger_at} if last else None
        ),
        "version": flow.version,
        "created_at": flow.created_at,
        "updated_at": flow.updated_at,
    }


def run_view(session, run, now=None):
    flow = session.get(PublishFlow, run.flow_id)
    graph = run.graph_snapshot_json
    preview = []
    if run.status == "awaiting_approval":
        approval = run.steps_json.get("_approval")
        if approval:
            preview = plan(graph, approval, now or utc_now())
    posts = {}
    for step in run.steps_json.values():
        identity = step.get("post_id") if isinstance(step, dict) else None
        if identity:
            post = session.get(PublishPost, identity)
            if post:
                posts[str(identity)] = {"status": post.status, "scheduled_at": post.scheduled_at}
    return {
        "id": run.id,
        "flow_id": run.flow_id,
        "flow_name": flow.name if flow else "",
        "brand_id": run.brand_id,
        "status": run.status,
        "trigger_at": run.trigger_at,
        "graph": graph,
        "current_node": run.current_node,
        "draft_post_id": run.draft_post_id,
        "approval_deadline": run.approval_deadline,
        "approved_at": run.approved_at,
        "steps": {key: value for key, value in run.steps_json.items() if not key.startswith("_")},
        "posts": posts,
        "plan": preview,
        "error": run.error,
        "finished_at": run.finished_at,
    }


# ── 流程 CRUD ─────────────────────────────────────────────


def audit(session, brand_id, action, actor, target_type, target_id, detail=None):
    session.add(
        AuditLog(
            actor=actor,
            brand_id=brand_id,
            action="flow." + action,
            target_type=target_type,
            target_id=target_id,
            detail_json=detail or {},
        )
    )


def get_flow(access, identity):
    flow = access.session.scalar(
        access.statement(PublishFlow).where(
            PublishFlow.id == identity, PublishFlow.deleted_at.is_(None)
        )
    )
    if not flow:
        raise HTTPException(404, "找不到流程")
    return flow


def get_run(access, identity):
    run = access.session.scalar(
        access.statement(PublishFlowRun).where(PublishFlowRun.id == identity)
    )
    if not run:
        raise HTTPException(404, "找不到流程執行紀錄")
    return run


def listing(access, brand_id=None):
    if brand_id:
        access.require_brand(brand_id)
    query = (
        access.statement(PublishFlow, brand_id)
        .where(PublishFlow.deleted_at.is_(None))
        .order_by(PublishFlow.id)
    )
    return [flow_view(access.session, flow) for flow in access.session.scalars(query)]


def detail(access, identity):
    return flow_view(access.session, get_flow(access, identity))


def schedule_next(flow, now):
    trigger = next(node for node in flow.graph_json.get("nodes", []) if node["type"] == "trigger")
    flow.next_run_at = next_trigger(parse_config(trigger), now)


def check_selected_posts(session, brand_id, graph):
    for node in graph.get("nodes", []):
        if node["type"] != "draft" or (node.get("config") or {}).get("source") != "post":
            continue
        post_id = node["config"].get("post_id")
        post = session.get(PublishPost, post_id) if post_id else None
        if post_id and (not post or post.brand_id != brand_id or post.status == "cancelled"):
            raise HTTPException(422, "選取的草稿不存在或已刪除")


def save(access, body, identity=None):
    session = access.session
    ensure_write(session)
    access.require_brand(body.brand_id, write=True)
    graph = body.graph.model_dump(mode="json")
    check_selected_posts(session, body.brand_id, graph)
    if identity is None:
        flow = PublishFlow(
            brand_id=body.brand_id,
            creator_id=access.staff.id,
            name=body.name,
            enabled=False,
            graph_json=graph,
        )
        session.add(flow)
        session.flush()
        action = "create"
    else:
        flow = get_flow(access, identity)
        if flow.version != body.version:
            raise HTTPException(409, "流程已更新，請重新整理")
        if flow.brand_id != body.brand_id:
            raise HTTPException(422, "不可更換流程品牌")
        if flow.enabled and not validate(graph)["ok"]:
            raise HTTPException(422, "流程啟用中，請先修正錯誤或停用後再存")
        flow.name, flow.graph_json = body.name, graph
        if flow.enabled:
            schedule_next(flow, utc_now())
        action = "update"
    flow.updated_at = utc_now()
    audit(session, flow.brand_id, action, f"staff:{access.staff.id}", "publish_flow", flow.id)
    session.commit()
    return flow_view(session, flow)


def delete(access, identity):
    session = access.session
    ensure_write(session)
    flow = get_flow(access, identity)
    access.require_brand(flow.brand_id, write=True)
    # 軟刪除：已觸發的執行與它們建立的貼文照常存在，可在發佈頁處理。
    flow.deleted_at, flow.enabled, flow.next_run_at = utc_now(), False, None
    audit(session, flow.brand_id, "delete", f"staff:{access.staff.id}", "publish_flow", flow.id)
    session.commit()
    return {"deleted": True}


def set_enabled(access, identity, body):
    session = access.session
    ensure_write(session)
    flow = get_flow(access, identity)
    access.require_brand(flow.brand_id, write=True)
    if flow.version != body.version:
        raise HTTPException(409, "流程已更新，請重新整理")
    if body.enabled:
        result = validate(flow.graph_json)
        if not result["ok"]:
            raise HTTPException(422, "流程還有錯誤，修正後才能啟用")
        schedule_next(flow, utc_now())
        if flow.next_run_at is None:
            raise HTTPException(422, "觸發時間已經過了，請改時間")
    else:
        flow.next_run_at = None
    flow.enabled = body.enabled
    audit(
        session,
        flow.brand_id,
        "enable",
        f"staff:{access.staff.id}",
        "publish_flow",
        flow.id,
        {"enabled": body.enabled},
    )
    session.commit()
    return flow_view(session, flow)


def runs(access, flow_id=None, brand_id=None, status=None, limit=50):
    if brand_id:
        access.require_brand(brand_id)
    query = access.statement(PublishFlowRun, brand_id).order_by(PublishFlowRun.id.desc())
    if flow_id is not None:
        get_flow(access, flow_id)
        query = query.where(PublishFlowRun.flow_id == flow_id)
    if status:
        query = query.where(PublishFlowRun.status == status)
    return [run_view(access.session, run) for run in access.session.scalars(query.limit(limit))]


def run_detail(access, identity):
    return run_view(access.session, get_run(access, identity))


# ── 通知 ─────────────────────────────────────────────────


def queue_line(session, brand_id, text):
    # 開頭沿用「發佈通知｜」：notify 只放行這種由工作檯自己產生、不含平台訊息的通知。
    policy, _, _ = notify.load_policy(session, brand_id)
    if not policy.enabled or not policy.group_id:
        return
    session.add(
        NotificationDelivery(
            brand_id=brand_id,
            retry_key=str(uuid4()),
            recipient=policy.group_id,
            messages_json=[{"type": "text", "text": text[:2000]}],
            next_attempt_at=utc_now(),
        )
    )


def flow_name(session, run):
    flow = session.get(PublishFlow, run.flow_id)
    return redact(flow.name if flow else "").text.replace("\n", " ")


def results_text(session, run):
    lines = []
    for node in chain(run.graph_snapshot_json):
        step = run.steps_json.get(node["id"], {})
        if node["type"] != "publish" or not step.get("post_id"):
            continue
        post = session.get(PublishPost, step["post_id"])
        names = "、".join(publish_rules.NAMES[p] for p in parse_config(node).platforms)
        status = STATUS_NAMES.get(post.status, "處理中") if post else "找不到貼文"
        lines.append(f"{names}：{status}")
    return lines


# ── 執行 ─────────────────────────────────────────────────


def mark(run, identity, status, **extra):
    steps = dict(run.steps_json)
    steps[identity] = {
        **steps.get(identity, {}),
        "status": status,
        "at": utc_now().isoformat(),
        **extra,
    }
    run.steps_json = steps


def fail(session, run, message):
    run.status, run.error, run.finished_at, run.wake_at = "failed", message, utc_now(), None
    if run.current_node:
        mark(run, run.current_node, "failed", error=message)
    text = f"發佈通知｜流程：{flow_name(session, run)}｜執行失敗\n{message}"
    queue_line(session, run.brand_id, text)


def next_idea(session, brand_id):
    used = {
        (row.report_id, row.idea_index)
        for row in session.execute(
            select(PublishPost.report_id, PublishPost.idea_index).where(
                PublishPost.brand_id == brand_id, PublishPost.report_id.is_not(None)
            )
        )
    }
    for report in session.scalars(
        select(IdeationReport)
        .where(IdeationReport.brand_id == brand_id, IdeationReport.status == "ready")
        .order_by(IdeationReport.id.desc())
        .limit(10)
    ):
        for index, idea in enumerate(report.data_json.get("ideas", [])):
            if (report.id, index) not in used:
                return report, index, idea
    return None


def copy_selected(session, settings, run, config):
    """每次執行複製一份選定的草稿（含素材），原稿保留下來當範本重複使用。"""
    source = session.get(PublishPost, config.post_id)
    if not source or source.brand_id != run.brand_id or source.status == "cancelled":
        return None
    created = session.info.setdefault("flow_media", [])
    post = copy_post(
        session,
        settings,
        source,
        dict(source.captions_json or {}),
        publish_platforms(run.graph_snapshot_json),
        created,
    )
    post.source_json = {"flow_id": run.flow_id, "flow_run_id": run.id, "copied_from": source.id}
    session.flush()
    detail = {"flow_run_id": run.id, "copied_from": source.id}
    publish.audit(session, post, "flow_draft", detail=detail)
    return post


def create_draft(session, flow_creator, run, node, settings=None):
    config = parse_config(node)
    if config.source == "post":
        return copy_selected(session, settings, run, config)
    caption, report_id, idea_index = config.caption, None, None
    if config.source == "idea":
        found = next_idea(session, run.brand_id)
        if not found:
            return None
        report, idea_index, idea = found
        report_id = report.id
        # 與主題發想建立草稿相同：只用標題、開場與 hashtag，不呼叫 AI。
        caption = publish.idea_caption(idea)
    post = PublishPost(
        brand_id=run.brand_id,
        creator_id=flow_creator,
        status="draft",
        format=config.format,
        source="flow",
        source_json={"flow_id": run.flow_id, "flow_run_id": run.id},
        caption=caption,
        platforms_json=publish_platforms(run.graph_snapshot_json),
        report_id=report_id,
        idea_index=idea_index,
    )
    options = deepcopy(publish_rules.DEFAULT_OPTIONS)
    options["threads"]["segments"] = [caption]
    post.platform_options_json = options
    session.add(post)
    session.flush()
    publish.audit(session, post, "flow_draft", detail={"flow_run_id": run.id})
    return post


def start(session, flow, now):
    """依 next_run_at 建立一次執行；太晚看到的記為已錯過，不補跑。"""
    due = flow.next_run_at
    graph = deepcopy(flow.graph_json)
    run = PublishFlowRun(
        flow_id=flow.id,
        brand_id=flow.brand_id,
        trigger_at=due,
        graph_snapshot_json=graph,
        steps_json={},
    )
    session.add(run)
    trigger = chain(graph)[0]
    schedule_next(flow, max(now, due))
    if now - due > MISSED_AFTER:
        run.status, run.finished_at = "missed", now
        session.flush()
        queue_line(
            session,
            flow.brand_id,
            f"發佈通知｜流程：{redact(flow.name).text}｜已錯過觸發時間，這次不補跑",
        )
        return run
    run.status = "running"
    run.current_node = after(graph, trigger["id"])
    session.flush()
    mark(run, trigger["id"], "done")
    run.steps_json = {**run.steps_json, "_creator": flow.creator_id}
    return run


def advance(session, run, now, settings=None):
    """核准前：一格一格往下走，遇到延遲或等待核准就停。"""
    graph = run.graph_snapshot_json
    while run.current_node:
        node = node_of(graph, run.current_node)
        kind = node["type"]
        if kind == "draft":
            post = create_draft(session, run.steps_json.get("_creator"), run, node, settings)
            if post is None:
                fail(
                    session,
                    run,
                    "選取的草稿已刪除"
                    if parse_config(node).source == "post"
                    else "沒有可用的主題發想題目",
                )
                return
            run.draft_post_id = post.id
            mark(run, node["id"], "done", post_id=post.id)
        elif kind == "delay":
            if run.wake_at is None:
                run.wake_at = apply_delay(parse_config(node), now)
                mark(run, node["id"], "waiting", until=run.wake_at.isoformat())
                return
            if run.wake_at > now:
                return
            run.wake_at = None
            mark(run, node["id"], "done")
        elif kind == "notify":
            message = parse_config(node).message.strip()
            queue_line(
                session,
                run.brand_id,
                f"發佈通知｜流程：{flow_name(session, run)}" + (f"\n{message}" if message else ""),
            )
            mark(run, node["id"], "done")
        elif kind == "approval":
            config = parse_config(node)
            run.status = "awaiting_approval"
            run.approval_deadline = now + timedelta(hours=config.hours)
            run.steps_json = {**run.steps_json, "_approval": node["id"]}
            mark(run, node["id"], "waiting")
            queue_line(
                session,
                run.brand_id,
                f"發佈通知｜流程：{flow_name(session, run)}｜有一篇草稿等你核准\n"
                f"請在 {config.hours} 小時內到工作檯「流程」頁核准",
            )
            return
        else:
            # 驗證保證發佈在核准之後；舊資料或手改資料走到這裡就停止，不送出任何東西。
            fail(session, run, "流程設定不正確")
            return
        run.current_node = after(graph, node["id"])
    finish(session, run)


def advance_scheduled(session, run):
    """核准後：等每個發佈方塊的貼文結束，再跑後面的通知。延遲已算進排程時間。"""
    graph = run.graph_snapshot_json
    while run.current_node:
        node = node_of(graph, run.current_node)
        kind = node["type"]
        if kind == "publish":
            step = run.steps_json.get(node["id"], {})
            post = session.get(PublishPost, step.get("post_id")) if step.get("post_id") else None
            if post and post.status not in POST_DONE:
                return
            mark(run, node["id"], post.status if post else "failed")
        elif kind == "notify":
            message = parse_config(node).message.strip()
            lines = [f"發佈通知｜流程：{flow_name(session, run)}"]
            if message:
                lines.append(message)
            lines += results_text(session, run)
            queue_line(session, run.brand_id, "\n".join(lines))
            mark(run, node["id"], "done")
        else:
            mark(run, node["id"], "done")
        run.current_node = after(graph, node["id"])
    finish(session, run)


def finish(session, run):
    statuses = []
    for node in chain(run.graph_snapshot_json):
        if node["type"] == "publish":
            step = run.steps_json.get(node["id"], {})
            post = session.get(PublishPost, step["post_id"]) if step.get("post_id") else None
            statuses.append(post.status if post else "failed")
    if not statuses or all(status == "done" for status in statuses):
        run.status = "done"
    elif any(status in {"done", "partial"} for status in statuses):
        run.status = "partial"
    else:
        run.status = "failed"
    run.finished_at, run.wake_at = utc_now(), None


def tick(factory, now=None, settings=None):
    now = now or utc_now()
    started = advanced = 0
    with factory.begin() as session:
        for flow in session.scalars(
            select(PublishFlow).where(
                PublishFlow.enabled.is_(True),
                PublishFlow.deleted_at.is_(None),
                PublishFlow.next_run_at <= now,
            )
        ):
            if not validate(flow.graph_json)["ok"]:
                flow.enabled, flow.next_run_at = False, None
                continue
            start(session, flow, now)
            started += 1
    with factory.begin() as session:
        ids = list(
            session.scalars(
                select(PublishFlowRun.id).where(PublishFlowRun.status.in_(sorted(RUN_OPEN)))
            )
        )
    for identity in ids:
        # 每次執行各自一個短交易：一筆壞資料不會擋住其他流程。
        copied = []
        try:
            with factory.begin() as session:
                session.info["flow_media"] = copied
                run = session.get(PublishFlowRun, identity)
                if run.status == "running" and (run.wake_at is None or run.wake_at <= now):
                    advance(session, run, now, settings)
                    advanced += 1
                elif run.status == "awaiting_approval" and run.approval_deadline <= now:
                    run.status, run.finished_at = "expired", now
                    queue_line(
                        session,
                        run.brand_id,
                        f"發佈通知｜流程：{flow_name(session, run)}｜超過核准期限，這次不發佈；"
                        "草稿留在發佈頁",
                    )
                elif run.status == "scheduled":
                    advance_scheduled(session, run)
        except Exception as error:
            # 交易已回滾，複製出來的素材檔沒有資料列指向，一併刪掉。
            for media in copied:
                remove_files(settings, media)
            log_failure("mwb.flows", "flow_run_failed", error)
    return {"started": started, "advanced": advanced}


# ── 核准與取消 ─────────────────────────────────────────────


def copy_post(session, settings, source, captions, platforms, created):
    post = PublishPost(
        brand_id=source.brand_id,
        creator_id=source.creator_id,
        status="draft",
        format=source.format,
        source="flow",
        source_json=dict(source.source_json),
        caption=source.caption,
        captions_json={k: v for k, v in captions.items() if k in platforms},
        platforms_json=list(platforms),
        facebook_unpublished=source.facebook_unpublished,
        report_id=source.report_id,
        idea_index=source.idea_index,
    )
    session.add(post)
    session.flush()
    mapping = {}
    for media in session.scalars(
        select(PublishMedia).where(
            PublishMedia.post_id == source.id, PublishMedia.deleted_at.is_(None)
        )
    ):
        # 每篇貼文各有一份檔案：發佈完成 30 天後各自清除，互不影響。
        root = settings.publish_media_root
        name = secrets.token_hex(24)
        shutil.copyfile(path_for(settings, media), root / name)
        copy = PublishMedia(
            post_id=post.id,
            position=media.position,
            original_name=media.original_name,
            relative_path=name,
            mime=media.mime,
            size=media.size,
            width=media.width,
            height=media.height,
            duration=media.duration,
            sha256=media.sha256,
            uploader_id=media.uploader_id,
            role=media.role,
        )
        session.add(copy)
        created.append(copy)
        session.flush()
        mapping[media.id] = copy.id
    options = deepcopy(source.platform_options_json or {})
    for platform, key in (
        ("youtube", "thumbnail_media_id"),
        ("instagram", "cover_media_id"),
        ("facebook", "cover_media_id"),
    ):
        values = options.get(platform)
        if isinstance(values, dict) and values.get(key):
            values[key] = mapping.get(values[key])
    post.platform_options_json = options
    return post


def approve(access, settings, identity, body):
    session = access.session
    ensure_write(session)
    run = get_run(access, identity)
    access.require_brand(run.brand_id, write=True)
    roles.require(access, "publish.submit")
    now = utc_now()
    if run.status != "awaiting_approval":
        raise HTTPException(409, "這次執行目前不需要核准")
    if run.approval_deadline <= now:
        raise HTTPException(409, "已超過核准期限")
    if not publish.enabled(session):
        raise HTTPException(409, "發佈功能未開啟")
    draft = session.get(PublishPost, run.draft_post_id) if run.draft_post_id else None
    if not draft or draft.status != "draft":
        raise HTTPException(409, "草稿已在發佈頁送出或刪除，無法由流程核准")
    if draft.version != body.post_version:
        raise HTTPException(409, "草稿已更新，請重新整理")
    graph = run.graph_snapshot_json
    approval = run.steps_json["_approval"]
    items = plan(graph, approval, now)
    if not items:
        raise HTTPException(422, "流程沒有發佈方塊")
    if items[-1]["at"] - now > MAX_SPAN:
        raise HTTPException(422, "整條流程最長 30 天，請縮短延遲")
    results = publish.checks(access, settings, draft.id)
    failures = []
    for item in items:
        for platform in item["platforms"]:
            if not results[platform]["ok"]:
                failures += results[platform]["reasons"] or [
                    f"{publish_rules.NAMES[platform]} 不符合發佈規則"
                ]
    if failures:
        raise HTTPException(422, "；".join(dict.fromkeys(failures)))
    created, posts = [], []
    captions = dict(draft.captions_json)
    try:
        for index, item in enumerate(items):
            if index == 0:
                # 第一個發佈方塊直接用草稿本身，其他方塊各複製一篇（含素材）。
                draft.platforms_json = list(item["platforms"])
                draft.captions_json = {k: v for k, v in captions.items() if k in item["platforms"]}
                post = draft
            else:
                post = copy_post(session, settings, draft, captions, item["platforms"], created)
            posts.append((item, post))
            mark(run, item["node"], "scheduled", post_id=post.id, at=item["at"].isoformat())
        mark(run, approval, "done")
        run.status, run.approved_at, run.approved_by = "scheduled", now, access.staff.id
        run.current_node = after(graph, approval)
        audit(
            session,
            run.brand_id,
            "run.approve",
            f"staff:{access.staff.id}",
            "publish_flow_run",
            run.id,
            {"posts": [post.id for _, post in posts]},
        )
        session.commit()
    except BaseException:
        session.rollback()
        for media in created:
            remove_files(settings, media)
        raise
    prepared = []
    try:
        for item, post in posts:
            session.refresh(post)
            publish.prepare(
                access,
                settings,
                post.id,
                PublishAction(confirmed=True, version=post.version, scheduled_at=item["at"]),
                via="flow",
            )
            prepared.append(post.id)
    except HTTPException as error:
        # 事先已檢查過規則；這裡失敗代表狀態在兩個交易之間被改了。已排好的撤回，整次標失敗。
        session.rollback()
        for post_id in prepared:
            try:
                publish.cancel(access, post_id)
            except HTTPException:
                pass
        ensure_write(session)
        run = session.get(PublishFlowRun, identity)
        fail(session, run, f"排程失敗：{error.detail}")
        session.commit()
        raise
    return run_view(session, session.get(PublishFlowRun, identity))


def cancel_run(access, identity):
    session = access.session
    ensure_write(session)
    run = get_run(access, identity)
    access.require_brand(run.brand_id, write=True)
    if run.status not in RUN_OPEN:
        raise HTTPException(409, "這次執行已經結束")
    skipped = []
    if run.status == "scheduled":
        for node in chain(run.graph_snapshot_json):
            step = run.steps_json.get(node["id"], {})
            post = session.get(PublishPost, step["post_id"]) if step.get("post_id") else None
            if not post or post.status not in {"scheduled", "paused"}:
                continue
            if publish.locked(post):
                # 一分鐘內就要送出的貼文已鎖定，跟發佈頁一樣不能取消。
                skipped.append(post.id)
                continue
            post.status, post.scheduled_at = "draft", None
            publish.release_pending(session, post)
            publish.audit(session, post, "cancel", f"staff:{access.staff.id}", {"via": "flow"})
    run.status, run.finished_at, run.wake_at = "cancelled", utc_now(), None
    audit(
        session,
        run.brand_id,
        "run.cancel",
        f"staff:{access.staff.id}",
        "publish_flow_run",
        run.id,
        {"locked_posts": skipped},
    )
    session.commit()
    return run_view(session, run)
