"""發文流程：流程只建立草稿與排程，送出一律經既有發佈與 HTTP mock。"""

from datetime import UTC, datetime, timedelta

import pytest
from conftest import login as shared_login
from cryptography.fernet import Fernet
from publish_http_mock import PlatformMock, seed_connections
from pydantic import SecretStr
from sqlalchemy import select

from app.models import (
    AuditLog,
    Brand,
    NotificationDelivery,
    PublishFlow,
    PublishFlowRun,
    PublishPost,
    Setting,
    Staff,
    StaffBrand,
)
from app.models.base import utc_now
from app.models.ideation import IdeationReport
from app.services import flows, notify, publish, publish_platforms
from app.services.passwords import hash_password


@pytest.fixture
def ready(client, settings, monkeypatch):
    settings.account_encryption_key = SecretStr(Fernet.generate_key().decode())
    settings.webhook_public_url = "https://public.example.test/webhook/meta-inbound"
    settings.publish_poll_seconds = 0.01
    settings.publish_poll_timeout = 0.03
    mock = PlatformMock()
    monkeypatch.setattr(publish_platforms, "client_factory", mock.client)
    password = SecretStr("isolated-flow-password")
    with client.app.state.session_factory.begin() as session:
        brand = Brand(slug="flow", name="隔離品牌")
        staff = Staff(
            username="flower",
            display_name="隔離管理員",
            role="admin",
            password_hash=hash_password(password),
        )
        session.add_all([brand, staff])
        session.flush()
        seed_connections(session, settings, brand.id)
        session.add(
            Setting(
                key=notify.policy_key(brand.id),
                value_json={"enabled": True, "group_id": "C" + "1" * 32},
            )
        )
        brand_id = brand.id
    client.headers.update(shared_login(client, "flower", password.get_secret_value(), origin=None))
    assert (
        client.put("/api/publish/switch", json={"enabled": True, "confirmed": True}).status_code
        == 200
    )
    return client, brand_id, mock


def node(identity, kind, **config):
    return {"id": identity, "type": kind, "position": {"x": 0, "y": 0}, "config": config}


def line(*nodes):
    return {
        "nodes": list(nodes),
        "edges": [
            {"source": a["id"], "target": b["id"]} for a, b in zip(nodes, nodes[1:], strict=False)
        ],
    }


def basic_graph(caption="隔離流程文案", delay=None, second=None):
    nodes = [
        node("t", "trigger", mode="daily", time="09:00"),
        node("d", "draft", source="template", format="text", caption=caption),
        node("a", "approval", hours=24),
        node("p1", "publish", platforms=["facebook"]),
    ]
    if delay:
        nodes.append(node("w", "delay", **delay))
    if second:
        nodes.append(node("p2", "publish", platforms=second))
    nodes.append(node("n", "notify", message="流程結束"))
    return line(*nodes)


def create_flow(ready, graph=None, enable=True):
    client, brand_id, _ = ready
    response = client.post(
        "/api/flows",
        json={"brand_id": brand_id, "name": "  每日貼文  ", "graph": graph or basic_graph()},
    )
    assert response.status_code == 201, response.text
    flow = response.json()
    assert flow["name"] == "每日貼文" and not flow["enabled"]
    if enable:
        response = client.post(
            f"/api/flows/{flow['id']}/enabled", json={"enabled": True, "version": flow["version"]}
        )
        assert response.status_code == 200, response.text
        flow = response.json()
    return flow


def fire(ready, flow, now=None):
    """把下次觸發拉到現在，再跑一次流程 tick。"""
    client = ready[0]
    factory = client.app.state.session_factory
    now = now or utc_now()
    with factory.begin() as session:
        session.get(PublishFlow, flow["id"]).next_run_at = now - timedelta(seconds=30)
    flows.tick(factory, now)
    with factory() as session:
        return session.scalar(
            select(PublishFlowRun)
            .where(PublishFlowRun.flow_id == flow["id"])
            .order_by(PublishFlowRun.id.desc())
        ).id


def approve(client, run_id):
    run = client.get(f"/api/flow-runs/{run_id}").json()
    post = client.get(f"/api/publish/posts/{run['draft_post_id']}").json()
    return client.post(
        f"/api/flow-runs/{run_id}/approve",
        json={"confirmed": True, "post_version": post["version"]},
    )


def flow_notices(client):
    with client.app.state.session_factory() as session:
        return [
            row.messages_json[0]["text"]
            for row in session.scalars(select(NotificationDelivery))
            if "流程：" in row.messages_json[0]["text"]
        ]


@pytest.mark.parametrize(
    "graph,expected",
    [
        (line(node("d", "draft", caption="x")), "流程需要剛好一個「時間觸發」"),
        (
            line(
                node("t", "trigger", mode="daily"),
                node("a", "approval"),
                node("d", "draft", caption="x"),
                node("p", "publish", platforms=["threads"]),
            ),
            "建立草稿必須在等待核准之前",
        ),
        (
            line(
                node("t", "trigger", mode="daily"),
                node("d", "draft", caption="x"),
                node("p", "publish", platforms=["threads"]),
                node("a", "approval"),
            ),
            "發佈之前必須先經過等待核准",
        ),
        (
            line(
                node("t", "trigger", mode="daily"),
                node("d", "draft", caption=""),
                node("a", "approval"),
                node("p", "publish", platforms=["threads"]),
            ),
            "請輸入範本文案",
        ),
        (
            line(
                node("t", "trigger", mode="daily"),
                node("d", "draft", caption="x"),
                node("a", "approval"),
                node("p", "publish", platforms=[]),
            ),
            "請至少選一個平台",
        ),
    ],
)
def test_validation_messages(graph, expected):
    result = flows.validate(graph)
    assert not result["ok"]
    assert expected in result["errors"] + [e for v in result["nodes"].values() for e in v]


def test_validation_rejects_branches_cycles_and_orphans():
    graph = basic_graph()
    graph["edges"].append({"source": "d", "target": "n"})
    assert "這一版每個方塊只能接一條出去的線" in flows.validate(graph)["nodes"]["d"]
    graph = basic_graph()
    graph["edges"].append({"source": "n", "target": "d"})
    assert not flows.validate(graph)["ok"]
    graph = basic_graph()
    graph["nodes"].append(node("x", "notify"))
    assert flows.validate(graph)["nodes"]["x"] == ["沒有接到流程上"]
    assert flows.validate(basic_graph())["ok"]


def test_next_trigger_uses_taipei_time():
    after = datetime(2026, 11, 2, 1, 30, tzinfo=UTC)  # 台北週一 09:30
    daily = flows.TriggerConfig(mode="daily", time="09:00")
    assert flows.next_trigger(daily, after) == datetime(2026, 11, 3, 1, 0, tzinfo=UTC)
    weekly = flows.TriggerConfig(mode="weekly", weekdays=[0, 4], time="20:00")
    assert flows.next_trigger(weekly, after) == datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
    once = flows.TriggerConfig(mode="once", date="2026-11-01", time="20:00")
    assert flows.next_trigger(once, after) is None


def test_plan_respects_lead_gap_and_clock_delay():
    base = datetime(2026, 11, 2, 1, 0, tzinfo=UTC)  # 台北 09:00
    graph = basic_graph(delay={"amount": 1, "unit": "minutes"}, second=["threads"])
    items = flows.plan(graph, "a", base)
    assert [item["at"] - base for item in items] == [timedelta(minutes=2), timedelta(minutes=3)]
    graph = basic_graph(delay={"at": "20:00"}, second=["threads"])
    assert flows.plan(graph, "a", base)[1]["at"] == datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def test_enabling_invalid_flow_is_rejected(ready):
    client, brand_id, _ = ready
    flow = create_flow(ready, graph=line(node("t", "trigger", mode="daily")), enable=False)
    assert not flow["validation"]["ok"]
    response = client.post(
        f"/api/flows/{flow['id']}/enabled", json={"enabled": True, "version": flow["version"]}
    )
    assert response.status_code == 422
    enabled = create_flow(ready)
    assert enabled["next_run_at"]
    response = client.put(
        f"/api/flows/{enabled['id']}",
        json={
            "brand_id": brand_id,
            "name": "壞掉",
            "graph": line(node("t", "trigger")),
            "version": enabled["version"],
        },
    )
    assert response.status_code == 422


def test_full_run_drafts_waits_for_approval_and_publishes_through_mock(ready, settings):
    client, _, mock = ready
    factory = client.app.state.session_factory
    flow = create_flow(ready, graph=basic_graph(second=["threads"]))
    run_id = fire(ready, flow)
    run = client.get(f"/api/flow-runs/{run_id}").json()
    assert run["status"] == "awaiting_approval"
    draft = client.get(f"/api/publish/posts/{run['draft_post_id']}").json()
    assert draft["status"] == "draft" and draft["source"] == "flow"
    assert draft["caption"] == "隔離流程文案" and draft["agent_source"] is None
    assert set(draft["platforms"]) == {"facebook", "threads"}
    assert [len(item["platforms"]) for item in run["plan"]] == [1, 1]
    assert any("等你核准" in text for text in flow_notices(client))
    assert mock.calls == []

    response = approve(client, run_id)
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["status"] == "scheduled"
    posts = [run["steps"][key]["post_id"] for key in ("p1", "p2")]
    assert posts[0] == run["draft_post_id"] and posts[1] != posts[0]
    with factory() as session:
        rows = [session.get(PublishPost, identity) for identity in posts]
        assert [row.status for row in rows] == ["scheduled", "scheduled"]
        assert [row.platforms_json for row in rows] == [["facebook"], ["threads"]]
        assert rows[1].scheduled_at - rows[0].scheduled_at >= timedelta(minutes=1)
        last = rows[1].scheduled_at
        actions = [row.action for row in session.scalars(select(AuditLog))]
    assert "flow.run.approve" in actions
    assert mock.calls == []

    publish.tick(factory, settings, last, wait=True)
    flows.tick(factory, last)
    run = client.get(f"/api/flow-runs/{run_id}").json()
    assert run["status"] == "done"
    assert {post["status"] for post in run["posts"].values()} == {"done"}
    assert any("流程結束" in text and "Threads：發佈成功" in text for text in flow_notices(client))


def test_approval_expires_without_publishing(ready):
    client, _, mock = ready
    flow = create_flow(ready)
    run_id = fire(ready, flow)
    flows.tick(client.app.state.session_factory, utc_now() + timedelta(hours=25))
    run = client.get(f"/api/flow-runs/{run_id}").json()
    assert run["status"] == "expired"
    assert client.get(f"/api/publish/posts/{run['draft_post_id']}").json()["status"] == "draft"
    assert approve(client, run_id).status_code == 409
    assert mock.calls == []


def test_missed_trigger_is_not_replayed(ready):
    client, _, mock = ready
    factory = client.app.state.session_factory
    flow = create_flow(ready)
    now = utc_now()
    with factory.begin() as session:
        session.get(PublishFlow, flow["id"]).next_run_at = now - timedelta(minutes=30)
    flows.tick(factory, now)
    runs = client.get(f"/api/flows/{flow['id']}/runs").json()
    assert [run["status"] for run in runs] == ["missed"]
    assert runs[0]["draft_post_id"] is None
    assert client.get(f"/api/flows/{flow['id']}").json()["next_run_at"] > now.isoformat()
    assert any("已錯過" in text for text in flow_notices(client))
    assert mock.calls == []


def test_approval_requires_publishing_switch(ready):
    client, _, _ = ready
    run_id = fire(ready, create_flow(ready))
    client.put("/api/publish/switch", json={"enabled": False, "confirmed": True})
    response = approve(client, run_id)
    assert response.status_code == 409 and response.json()["detail"] == "發佈功能未開啟"


def test_cancel_scheduled_run_returns_posts_to_draft(ready):
    client, _, mock = ready
    run_id = fire(ready, create_flow(ready, graph=basic_graph(second=["threads"])))
    assert approve(client, run_id).status_code == 200
    response = client.post(f"/api/flow-runs/{run_id}/cancel")
    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "cancelled"
    assert {post["status"] for post in run["posts"].values()} == {"draft"}
    assert client.post(f"/api/flow-runs/{run_id}/cancel").status_code == 409
    assert mock.calls == []


def test_idea_source_uses_next_unused_idea(ready):
    client, brand_id, _ = ready
    with client.app.state.session_factory.begin() as session:
        now = utc_now()
        session.add(
            IdeationReport(
                brand_id=brand_id,
                meeting_at=now,
                start_at=now,
                end_at=now,
                trigger="manual",
                provider="fixture",
                status="ready",
                data_json={"ideas": [{"title": "第一題", "hook": "開場", "keyword": "服務"}]},
            )
        )
    graph = basic_graph()
    graph["nodes"][1]["config"] = {"source": "idea", "format": "text"}
    flow = create_flow(ready, graph=graph)
    first = client.get(f"/api/flow-runs/{fire(ready, flow)}").json()
    draft = client.get(f"/api/publish/posts/{first['draft_post_id']}").json()
    assert draft["caption"].startswith("第一題")
    second = client.get(f"/api/flow-runs/{fire(ready, flow)}").json()
    assert second["status"] == "failed" and second["error"] == "沒有可用的主題發想題目"


@pytest.mark.parametrize(
    "role,assigned,expected",
    [("viewer", True, 403), ("marketing", False, 404), ("marketing", True, 201)],
)
def test_roles_and_brand_scope(ready, role, assigned, expected):
    client, brand_id, _ = ready
    with client.app.state.session_factory.begin() as session:
        staff = session.scalar(select(Staff).where(Staff.username == "flower"))
        staff.role = role
        if assigned:
            session.add(StaffBrand(staff_id=staff.id, brand_id=brand_id))
    response = client.post(
        "/api/flows", json={"brand_id": brand_id, "name": "權限", "graph": basic_graph()}
    )
    assert response.status_code == expected


def test_deleted_flow_stops_triggering(ready):
    client, _, _ = ready
    factory = client.app.state.session_factory
    flow = create_flow(ready)
    assert client.delete(f"/api/flows/{flow['id']}").status_code == 200
    assert client.get(f"/api/flows/{flow['id']}").status_code == 404
    with factory.begin() as session:
        session.get(PublishFlow, flow["id"]).next_run_at = utc_now() - timedelta(minutes=1)
    flows.tick(factory)
    with factory() as session:
        assert session.scalar(select(PublishFlowRun)) is None


def selected_graph(post_id):
    graph = basic_graph()
    graph["nodes"][1] = node("d", "draft", source="post", post_id=post_id)
    return graph


def test_selected_draft_is_copied_each_run(ready):
    client, brand_id, _ = ready
    factory = client.app.state.session_factory
    with factory.begin() as session:
        staff = session.scalar(select(Staff).where(Staff.username == "flower"))
        source = PublishPost(
            brand_id=brand_id,
            creator_id=staff.id,
            status="draft",
            format="text",
            caption="[隔離] 選定草稿",
            captions_json={"facebook": "[隔離] FB 專屬"},
            platforms_json=["facebook"],
        )
        session.add(source)
        session.flush()
        source_id = source.id
    missing = selected_graph(None)
    assert flows.validate(missing)["nodes"]["d"] == ["請選擇草稿"]
    flow = create_flow(ready, selected_graph(source_id))
    first = fire(ready, flow)
    run = client.get(f"/api/flow-runs/{first}").json()
    assert run["status"] == "awaiting_approval"
    copy = client.get(f"/api/publish/posts/{run['draft_post_id']}").json()
    assert copy["id"] != source_id and copy["caption"] == "[隔離] 選定草稿"
    assert approve(client, first).status_code == 200
    with factory() as session:
        assert session.get(PublishPost, source_id).status == "draft"
        copied = session.get(PublishPost, run["draft_post_id"])
        assert copied.source_json["copied_from"] == source_id
    # 原稿刪除後，下一次執行失敗並說明原因，不會送出任何東西。
    with factory.begin() as session:
        session.get(PublishPost, source_id).status = "cancelled"
    second = fire(ready, flow, utc_now() + timedelta(days=1))
    with factory() as session:
        failed = session.get(PublishFlowRun, second)
        assert failed.status == "failed" and failed.error == "選取的草稿已刪除"


def test_selected_draft_must_belong_to_brand(ready):
    client, brand_id, _ = ready
    with client.app.state.session_factory.begin() as session:
        other = Brand(slug="other-flow", name="其他品牌")
        staff = session.scalar(select(Staff).where(Staff.username == "flower"))
        session.add(other)
        session.flush()
        post = PublishPost(brand_id=other.id, creator_id=staff.id, status="draft", format="text")
        session.add(post)
        session.flush()
        post_id = post.id
    body = {"brand_id": brand_id, "name": "跨品牌", "graph": selected_graph(post_id)}
    response = client.post("/api/flows", json=body)
    assert response.status_code == 422 and response.json()["detail"] == "選取的草稿不存在或已刪除"
