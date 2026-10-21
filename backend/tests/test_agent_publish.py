"""Agent publication contracts; all outbound requests use synthetic HTTP transport."""

import asyncio
import json
import secrets
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import Mock
from urllib.parse import urlsplit

import httpx
import pytest
import uvicorn
from cryptography.fernet import Fernet
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from publish_http_mock import (
    PlatformMock,
    jpeg_bytes,
    seed_connections,
    seed_youtube,
    video_bytes,
)
from pydantic import SecretStr
from sqlalchemy import select, update
from test_agent_auth import agent_client  # noqa: F401

from app.models import AuditLog, Brand, PublishPost, PublishTarget, Setting, Staff
from app.models.agent_auth import AgentCredential, AgentGrant
from app.models.agent_publish import AgentPublishConfirmation, AgentUpload
from app.models.base import utc_now
from app.models.ideation import IdeationReport
from app.services import agent_auth, agent_publish, agent_tools, ai, publish


@pytest.fixture
def posting(request, monkeypatch):
    client = request.getfixturevalue("agent_client")
    factory, settings = client.app.state.session_factory, client.app.state.settings
    settings.account_encryption_key = SecretStr(Fernet.generate_key().decode())
    settings.webhook_public_url = "https://public.example.test/webhook/meta-inbound"
    from app.services import publish_platforms

    mock = PlatformMock()
    monkeypatch.setattr(publish_platforms, "client_factory", mock.client)
    monkeypatch.setattr(agent_publish, "kickoff", lambda *a: publish.execute(*a))
    monkeypatch.setattr(ai, "run", Mock(side_effect=AssertionError("AI forbidden")))
    with factory.begin() as session:
        seed_connections(session, settings, client.brand_id)
        session.add(Setting(key="publishing.enabled", value_json={"enabled": True}))
        hidden = Brand(slug="hidden-publish", name="其他品牌")
        session.add(hidden)
        session.flush()
        client.hidden_brand = hidden.id
        client.grants = {}
        for role, user in [
            ("admin", "agent-owner"),
            ("marketing", "agent-marketer"),
            ("viewer", "agent-reader"),
        ]:
            row = AgentGrant(staff_id=client.ids[user], kind="token", name="隔離 Agent 發佈")
            session.add(row)
            session.flush()
            client.grants[role] = row.id
    client.mock = mock
    return client


def invoke(client, name, args=None, role="admin"):
    return agent_tools.dispatch(
        client.app.state.session_factory,
        client.app.state.settings,
        client.grants[role],
        name,
        args or {},
        str(client.base_url).rstrip("/"),
    )


def ok(client, name, args=None, role="admin"):
    result = invoke(client, name, args, role)
    assert not result.isError, result
    return result.structuredContent


def draft(client, role="admin", **changes):
    return ok(
        client,
        "save_publish_draft",
        {
            "brand_id": client.brand_id,
            "format": "text",
            "caption": "確認需求後安排內容。",
            "platforms": ["facebook", "threads"],
            **changes,
        },
        role,
    )


def prepared(client, post, **changes):
    return ok(
        client, "prepare_publish", {"post_id": post["id"], "version": post["version"], **changes}
    )


def confirm(client, post, prep, role="admin"):
    return invoke(
        client,
        "confirm_publish",
        {"post_id": post["id"], "confirmation_code": prep["confirmation_code"]},
        role,
    )


@pytest.mark.parametrize("role", ["admin", "marketing", "viewer"])
def test_all_tools_permissions_and_audit(posting, role):
    post = draft(posting)
    args = {
        "list_publish_posts": {"brand_id": posting.brand_id},
        "get_publish_options": {"brand_id": posting.brand_id},
        "get_publish_post": {"post_id": post["id"]},
        "save_publish_draft": {
            "brand_id": posting.brand_id,
            "format": "text",
            "caption": "隔離內容",
            "platforms": ["facebook"],
        },
        "create_draft_from_idea": {"report_id": 99999, "idea_index": 0, "caption": "內容"},
        "create_upload_link": {"post_id": post["id"], "filename": "test.png"},
        "remove_publish_media": {"post_id": post["id"], "media_id": 99999},
        "delete_publish_draft": {"post_id": 99999},
        "prepare_publish": {"post_id": post["id"], "version": post["version"]},
        "confirm_publish": {"post_id": post["id"], "confirmation_code": "not-prepared"},
        "retry_failed_platforms": {"post_id": post["id"], "version": post["version"]},
        "cancel_schedule": {"post_id": post["id"]},
    }
    assert set(args) == set(agent_tools.PUBLISH_SPECS)
    for name, body in args.items():
        result = invoke(posting, name, body, role)
        write = agent_tools.SPECS[name][1]
        if role == "viewer" and write:
            assert result.isError and "行銷或管理員" in result.content[0].text
        elif not write or name in {"save_publish_draft", "create_upload_link", "prepare_publish"}:
            assert not result.isError, result
        else:
            assert result.isError  # Valid identity, invalid domain target/state.
        with posting.app.state.session_factory() as session:
            audit = session.scalar(
                select(AuditLog)
                .where(AuditLog.action.in_(["agent.tool.read", "agent.tool.write"]))
                .order_by(AuditLog.id.desc())
            )
            assert audit.detail_json["tool"] == name
            assert audit.actor == f"staff:{session.get(AgentGrant, posting.grants[role]).staff_id}"
            assert set(audit.detail_json) == {"tool", "connection_name", "grant_id", "result"}


def test_brand_version_safety_and_pagination(posting):
    post = draft(posting)
    for name in ["list_publish_posts", "get_publish_options", "save_publish_draft"]:
        args = {"brand_id": posting.hidden_brand}
        if name == "save_publish_draft":
            args |= {"format": "text", "caption": "內容", "platforms": ["facebook"]}
        result = invoke(posting, name, args, "marketing")
        assert result.isError and "找不到" in result.content[0].text
    with posting.app.state.session_factory.begin() as session:
        row = session.get(PublishPost, post["id"])
        row.brand_id = posting.hidden_brand
    assert invoke(posting, "get_publish_post", {"post_id": post["id"]}, "marketing").isError
    post = draft(posting)
    args = {
        "brand_id": posting.brand_id,
        "post_id": post["id"],
        "version": 999,
        "format": "text",
        "caption": "新內容",
        "platforms": ["facebook"],
    }
    assert invoke(posting, "save_publish_draft", args).isError
    with posting.app.state.session_factory.begin() as session:
        from app.services.branding import put_setting

        put_setting(session, f"brand.rules.{posting.brand_id}", {"forbidden_phrases": ["達成效果"]})
    for field in ["caption", "platform_captions"]:
        args["version"] = post["version"]
        args[field] = "保證達成效果" if field == "caption" else {"threads": "保證達成效果"}
        result = invoke(posting, "save_publish_draft", args)
        assert result.isError and "caption" in result.content[0].text
        args["caption"] = "新內容"
    blank = draft(posting, caption="", platforms=[])
    draft(posting)
    listing = ok(
        posting, "list_publish_posts", {"brand_id": posting.brand_id, "limit": 1}, "viewer"
    )
    assert len(listing["items"]) == 1 and listing["next_offset"] == 1
    assert blank["id"] not in [
        p["id"] for p in ok(posting, "list_publish_posts", {"brand_id": posting.brand_id})["items"]
    ]


@pytest.mark.parametrize(
    "change", ["expired", "used", "member", "version", "hash", "off", "account", "media"]
)
def test_confirmation_invalidated(posting, change):
    post = draft(posting)
    prep = prepared(posting, post)
    assert not posting.mock.calls  # Preparing never contacts the provider.
    with posting.app.state.session_factory.begin() as session:
        row = session.scalar(select(AgentPublishConfirmation))
        if change == "expired":
            row.expires_at = utc_now() - timedelta(seconds=1)
        elif change == "used":
            row.used_at = utc_now()
        elif change == "version":
            session.get(PublishPost, post["id"]).caption = "修改"
        elif change == "hash":
            session.execute(
                update(PublishPost).where(PublishPost.id == post["id"]).values(caption="修改")
            )
        elif change == "off":
            session.scalar(
                select(Setting).where(Setting.key == "publishing.enabled")
            ).value_json = {"enabled": False}
        elif change == "account":
            from app.models import Account

            session.scalar(select(Account).where(Account.external_id == "100")).name = "新帳號名稱"
        elif change == "media":
            session.execute(
                update(PublishPost).where(PublishPost.id == post["id"]).values(format="image")
            )
    result = confirm(posting, post, prep, "marketing" if change == "member" else "admin")
    assert result.isError and "重新 prepare_publish" in result.content[0].text
    assert not posting.mock.calls


def test_success_replay_schedule_cancel_lock_and_immutable(posting):
    post = draft(posting)
    assert invoke(
        posting, "confirm_publish", {"post_id": post["id"], "confirmation_code": "none"}
    ).isError
    prep = prepared(posting, post)
    assert not confirm(posting, post, prep).isError
    assert confirm(posting, post, prep).isError
    assert ok(posting, "get_publish_post", {"post_id": post["id"]})["status"] == "done"
    for name, extra in [
        (
            "save_publish_draft",
            {
                "brand_id": posting.brand_id,
                "format": "text",
                "caption": "改",
                "platforms": [],
                "version": post["version"],
            },
        ),
        ("delete_publish_draft", {}),
        ("create_upload_link", {"filename": "a.png"}),
        ("remove_publish_media", {"media_id": 1}),
        ("cancel_schedule", {}),
        ("prepare_publish", {"version": post["version"]}),
    ]:
        assert invoke(posting, name, {"post_id": post["id"], **extra}).isError
    post = draft(posting)
    prep = prepared(posting, post, scheduled_at=(utc_now() + timedelta(hours=2)).isoformat())
    assert prep["details"]["scheduled_at"].endswith("+08:00")
    assert not confirm(posting, post, prep).isError
    current = ok(posting, "get_publish_post", {"post_id": post["id"]})
    assert current["status"] == "scheduled"
    assert invoke(
        posting,
        "save_publish_draft",
        {
            "post_id": post["id"],
            "version": current["version"],
            "brand_id": posting.brand_id,
            "format": "text",
            "caption": "改",
            "platforms": [],
        },
    ).isError
    assert ok(posting, "cancel_schedule", {"post_id": post["id"]})["status"] == "draft"
    current = ok(posting, "get_publish_post", {"post_id": post["id"]})
    prep = prepared(posting, current, scheduled_at=(utc_now() + timedelta(hours=2)).isoformat())
    assert not confirm(posting, current, prep).isError
    with posting.app.state.session_factory.begin() as session:
        session.get(PublishPost, post["id"]).scheduled_at = utc_now() + timedelta(seconds=30)
    assert invoke(posting, "cancel_schedule", {"post_id": post["id"]}).isError


def test_retry_only_failed_and_actor(posting):
    post = draft(posting)
    posting.mock.fail_threads = True
    assert not confirm(posting, post, prepared(posting, post)).isError
    current = ok(posting, "get_publish_post", {"post_id": post["id"]})
    assert current["status"] == "partial"
    posting.mock.calls.clear()
    posting.mock.fail_threads = False
    prep = ok(
        posting, "retry_failed_platforms", {"post_id": post["id"], "version": current["version"]}
    )
    assert set(prep["details"]["accounts"]) == {"threads"}
    assert not confirm(posting, current, prep).isError
    assert all(host == "graph.threads.net" for _, host, _ in posting.mock.calls)
    with posting.app.state.session_factory() as session:
        rows = list(
            session.scalars(
                select(AuditLog).where(
                    AuditLog.target_id == post["id"],
                    AuditLog.action.in_(["publish.confirm", "publish.result", "publish.attempt"]),
                )
            )
        )
        assert rows and all(
            r.actor == f"staff:{posting.ids['agent-owner']}"
            and r.detail_json["via"] == "隔離 Agent 發佈"
            for r in rows
        )
        assert prep["confirmation_code"] not in json.dumps([r.detail_json for r in rows])


@pytest.mark.parametrize(
    "case", ["valid", "expired", "invalid", "format", "size", "disabled", "viewer"]
)
def test_upload_one_use_boundary_and_validation(posting, case):
    post = draft(posting, format="image")
    link = ok(posting, "create_upload_link", {"post_id": post["id"], "filename": "test.jpg"})
    path = urlsplit(link["upload_url"]).path
    assert "curl.exe -T" in link["instructions"]
    assert posting.put(path, content=jpeg_bytes(), headers={"X-MWB-Public": "1"}).status_code == 404
    with posting.app.state.session_factory.begin() as session:
        row = session.scalar(select(AgentUpload))
        assert urlsplit(path).path.split("/")[-1] != row.token_hash
        if case == "expired":
            row.expires_at = utc_now() - timedelta(seconds=1)
        elif case in {"disabled", "viewer"}:
            staff = session.get(Staff, posting.ids["agent-owner"])
            if case == "disabled":
                staff.active = False
            else:
                staff.role = "viewer"
    content = jpeg_bytes()
    if case == "format":
        content = b"invalid content format"
    elif case == "size":
        content += bytes(8 * 1024**2)
    elif case == "invalid":
        path = "/api/agent/uploads/unknown"
    response = posting.put(path, content=content)
    expected = {
        "valid": 200,
        "expired": 410,
        "invalid": 410,
        "format": 422,
        "size": 413,
        "disabled": 401,
        "viewer": 403,
    }[case]
    assert response.status_code == expected, response.text
    if case in {"valid", "format", "size", "expired"}:
        assert posting.put(path, content=content).status_code == 410
    if case == "valid":
        media = ok(posting, "get_publish_post", {"post_id": post["id"]})["media"]
        assert (
            len(media) == 1 and media[0]["mime"] == "image/jpeg" and "relative_path" not in media[0]
        )


def test_idea_uses_caption_without_ai(posting):
    with posting.app.state.session_factory.begin() as session:
        row = IdeationReport(
            brand_id=posting.brand_id,
            meeting_at=utc_now(),
            trigger="manual",
            provider="agent",
            start_at=utc_now(),
            end_at=utc_now(),
            status="ready",
            data_json={"ideas": [{"title": "主題", "keyword": "測試"}]},
        )
        session.add(row)
        session.flush()
        identity = row.id
    body = {"report_id": identity, "idea_index": 0, "caption": "Agent 定案文案"}
    first = ok(posting, "create_draft_from_idea", body)
    second = ok(posting, "create_draft_from_idea", {**body, "caption": "不覆寫"})
    assert first["created"] and not second["created"]
    assert first["post"]["id"] == second["post"]["id"]
    assert second["post"]["caption"] == body["caption"]
    assert "caption_job" not in second["post"]
    ai.run.assert_not_called()


def test_confirmation_atomic_replay_long_caption_and_media_edit(posting):
    post = draft(posting, platforms=["facebook"], caption="完整文案\n" * 1800)
    assert ok(posting, "get_publish_post", {"post_id": post["id"]})["caption"] == post["caption"]
    prep = prepared(posting, post)
    assert prep["details"]["caption"] == post["caption"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: confirm(posting, post, prep), range(2)))
    assert sum(not r.isError for r in results) == 1
    assert sum(method == "POST" for method, _, _ in posting.mock.calls) == 1
    post = draft(posting, format="image", platforms=["facebook"])
    link = ok(posting, "create_upload_link", {"post_id": post["id"], "filename": "image.jpg"})
    assert posting.put(link["upload_url"], content=jpeg_bytes()).status_code == 200
    post = ok(posting, "get_publish_post", {"post_id": post["id"]})
    prep = prepared(posting, post)
    removed = ok(
        posting, "remove_publish_media", {"post_id": post["id"], "media_id": post["media"][0]["id"]}
    )
    assert not removed["media"] and confirm(posting, post, prep).isError
    assert ok(posting, "delete_publish_draft", {"post_id": post["id"]})["status"] == "cancelled"


def test_upload_rechecks_member_after_stream_and_cleanup(posting):
    factory = posting.app.state.session_factory
    post = draft(posting, format="image")
    link = ok(posting, "create_upload_link", {"post_id": post["id"], "filename": "image.jpg"})

    def stream():
        yield jpeg_bytes()
        with factory.begin() as session:
            session.get(Staff, posting.ids["agent-owner"]).active = False

    assert posting.put(link["upload_url"], content=stream()).status_code == 401
    with factory.begin() as session:
        from app.models import PublishMedia

        assert not session.scalar(select(PublishMedia))
        row = session.scalar(select(AgentUpload))
        row.expires_at = utc_now() - timedelta(seconds=1)
    agent_auth.maintain(factory)
    with factory() as session:
        assert not session.scalar(select(AgentUpload))


def test_annotations_and_urls_keep_private_paths_redacted():
    from app.services import agent_queries

    value = "http://127.0.0.1:8123/api/agent/uploads/abc"
    assert agent_queries.safe_text(value) == value
    assert "private" not in agent_queries.safe_text("C:/private/example.jpg")
    tools = {t.name: t for t in agent_tools.list_tools()}
    assert tools["confirm_publish"].annotations.destructiveHint
    assert tools["confirm_publish"].annotations.openWorldHint
    for name, (_, write, _) in agent_tools.PUBLISH_SPECS.items():
        assert tools[name].annotations.readOnlyHint is not write
        assert "下一步" in tools[name].description


def test_strict_publishing_inputs(posting):
    post = draft(posting)
    rules = ok(posting, "get_publish_options", {"brand_id": posting.brand_id})["rules"]
    assert rules["instagram"]["image_width"] == [320, 1440]
    assert rules["instagram"]["image_ratio"] == [0.8, 1.91]
    assert rules["threads"]["media_count"]["carousel"] == {"min": 2, "max": 20}
    assert rules["threads"]["carousel_types"] == ["image", "video"]
    for value in (True, 1_900_000_000, "2030-01-01T12:00:00"):
        result = invoke(
            posting,
            "prepare_publish",
            {
                "post_id": post["id"],
                "version": post["version"],
                "scheduled_at": value,
            },
        )
        assert result.isError
    for value in (True, "0", 0.5):
        result = invoke(
            posting,
            "create_draft_from_idea",
            {
                "report_id": 1,
                "idea_index": value,
                "caption": "隔離文案",
            },
        )
        assert result.isError


def test_sdk_upload_prepare_confirm_end_to_end(posting):
    factory = posting.app.state.session_factory
    token = secrets.token_urlsafe(32)
    with factory.begin() as session:
        session.add(
            AgentCredential(
                token_hash=agent_auth.digest(token),
                grant_id=posting.grants["admin"],
                kind="token",
                expires_at=utc_now() + timedelta(days=1),
            )
        )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(posting.app, log_level="error", access_log=False))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started

        async def scenario():
            origin = f"http://127.0.0.1:{port}"
            async with httpx.AsyncClient(headers={"Authorization": "Bearer " + token}) as client:
                async with streamable_http_client(origin + "/mcp", http_client=client) as streams:
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()

                        async def call(name, args):
                            result = await session.call_tool(name, args)
                            assert not result.isError, result
                            return result.structuredContent

                        post = await call(
                            "save_publish_draft",
                            {
                                "brand_id": posting.brand_id,
                                "format": "image",
                                "caption": "隔離SDK驗收",
                                "platforms": ["facebook"],
                            },
                        )
                        link = await call(
                            "create_upload_link", {"post_id": post["id"], "filename": "test.jpg"}
                        )
                        assert link["upload_url"].startswith(origin)
                        response = await client.put(link["upload_url"], content=jpeg_bytes())
                        assert response.status_code == 200, response.text
                        post = await call("get_publish_post", {"post_id": post["id"]})
                        prep = await call(
                            "prepare_publish", {"post_id": post["id"], "version": post["version"]}
                        )
                        await call(
                            "confirm_publish",
                            {"post_id": post["id"], "confirmation_code": prep["confirmation_code"]},
                        )
                        result = await call("get_publish_post", {"post_id": post["id"]})
                        assert (
                            result["status"] == "done"
                            and result["targets"][0]["status"] == "succeeded"
                        )

        asyncio.run(scenario())
    finally:
        server.should_exit = True
        worker.join(10)
        sock.close()
        assert not worker.is_alive()


def test_publish_result_permalinks_keep_brand_handle(posting):
    post = draft(posting)
    assert not confirm(posting, post, prepared(posting, post)).isError
    links = {
        "threads": "https://www.threads.com/@brandhandle/post/abc",
        "facebook": "http://insecure.example.test/post",
    }
    with posting.app.state.session_factory.begin() as session:
        for target in session.scalars(select(PublishTarget)):
            target.permalink = links.get(target.platform, target.permalink)
    for name, args in (
        ("get_publish_post", {"post_id": post["id"]}),
        ("list_publish_posts", {"brand_id": posting.brand_id}),
    ):
        result = ok(posting, name, args, "viewer")
        targets = result["targets"] if name == "get_publish_post" else result["items"][0]["targets"]
        shown = {t["platform"]: t["permalink"] for t in targets}
        # 品牌自己的 Threads 網址含 @帳號，不能被觀眾遮蔽弄壞；非 https 網址不外露。
        assert shown["threads"] == links["threads"]
        assert shown["facebook"] is None


def test_deleted_at_in_publish_results_and_tool_descriptions(posting):
    post = draft(posting)
    assert not confirm(posting, post, prepared(posting, post)).isError
    with posting.app.state.session_factory.begin() as session:
        for target in session.scalars(select(PublishTarget)):
            if target.platform == "facebook":
                target.deleted_at = utc_now()
    listed = ok(posting, "list_publish_posts", {"brand_id": posting.brand_id}, "viewer")
    shown = {t["platform"]: t["deleted_at"] for t in listed["items"][0]["targets"]}
    assert shown["facebook"].endswith("+08:00") and shown["threads"] is None
    detail = ok(posting, "get_publish_post", {"post_id": post["id"]}, "viewer")
    assert {t["platform"]: t["deleted_at"] is not None for t in detail["targets"]} == {
        "facebook": True,
        "threads": False,
    }
    specs = agent_tools.PUBLISH_SPECS
    for name in ("list_publish_posts", "get_publish_post"):
        assert "deleted_at 有值代表貼文已在平台上被刪除" in specs[name][2]


def test_facebook_unpublished_tools_read_write_and_default(posting):
    saved = draft(posting, facebook_unpublished=True)
    assert saved["facebook_unpublished"] is True
    assert draft(posting)["facebook_unpublished"] is False
    shown = ok(posting, "get_publish_post", {"post_id": saved["id"]}, "viewer")
    assert shown["facebook_unpublished"] is True
    items = ok(posting, "list_publish_posts", {"brand_id": posting.brand_id}, "viewer")["items"]
    assert {row["id"]: row["facebook_unpublished"] for row in items}[saved["id"]] is True

    def update(post, **changes):
        return invoke(
            posting,
            "save_publish_draft",
            {
                "brand_id": posting.brand_id,
                "post_id": post["id"],
                "version": post["version"],
                "format": "text",
                "caption": "更新文案",
                "platforms": ["facebook", "threads"],
                **changes,
            },
        )

    # 更新時省略選項沿用原值，不會因為只改文案而變成公開。
    kept = update(saved)
    assert not kept.isError and kept.structuredContent["facebook_unpublished"] is True
    # 平台不含 Facebook：明確要求不公開是矛盾，省略則選項自然失效。
    contradiction = update(kept.structuredContent, platforms=["threads"], facebook_unpublished=True)
    assert contradiction.isError
    assert update(kept.structuredContent, facebook_unpublished="yes").isError
    assert update(kept.structuredContent, facebook_unpublished=1).isError
    dropped = update(kept.structuredContent, platforms=["threads"])
    assert dropped.structuredContent["facebook_unpublished"] is False
    again = update(dropped.structuredContent, platforms=["facebook"], facebook_unpublished=True)
    assert again.structuredContent["facebook_unpublished"] is True
    off = update(again.structuredContent, platforms=["facebook"], facebook_unpublished=False)
    assert off.structuredContent["facebook_unpublished"] is False


def facebook_requests(mock):
    return [
        fields
        for method, _, path, fields in mock.requests
        if method == "POST" and "/v26.0/100/" in path
    ]


def test_facebook_unpublished_change_invalidates_confirmation_and_publishes_hidden(posting):
    factory = posting.app.state.session_factory
    post = draft(posting, facebook_unpublished=True)
    prep = prepared(posting, post)
    assert prep["details"]["facebook_unpublished"] is True
    assert not posting.mock.calls
    # 只改選項（不改版本）：明細指紋改變，舊確認碼失效。
    with factory.begin() as session:
        session.execute(
            update(PublishPost)
            .where(PublishPost.id == post["id"])
            .values(facebook_unpublished=False)
        )
    result = confirm(posting, post, prep)
    assert result.isError and "重新 prepare_publish" in result.content[0].text
    assert not posting.mock.calls
    # 透過工具改選項會提高版本，同樣使舊確認碼失效。
    current = ok(posting, "get_publish_post", {"post_id": post["id"]})
    prep = prepared(posting, current)
    assert prep["details"]["facebook_unpublished"] is False
    changed = ok(
        posting,
        "save_publish_draft",
        {
            "brand_id": posting.brand_id,
            "post_id": post["id"],
            "version": current["version"],
            "format": "text",
            "caption": current["caption"],
            "platforms": ["facebook", "threads"],
            "facebook_unpublished": True,
        },
    )
    result = confirm(posting, changed, prep)
    assert result.isError and "重新 prepare_publish" in result.content[0].text
    assert not posting.mock.calls
    # 重新準備後確認：Facebook 以未發佈貼文建立，Threads 照常公開。
    prep = prepared(posting, changed)
    assert prep["details"]["facebook_unpublished"] is True
    assert not confirm(posting, changed, prep).isError
    assert facebook_requests(posting.mock) == [
        {
            "message": "確認需求後安排內容。",
            "published": "false",
            "unpublished_content_type": "DRAFT",
        }
    ]
    threads = [
        fields
        for method, host, _, fields in posting.mock.requests
        if method == "POST" and host == "graph.threads.net"
    ]
    assert threads and not any("published" in fields for fields in threads)
    done = ok(posting, "get_publish_post", {"post_id": post["id"]})
    assert done["status"] == "done" and done["facebook_unpublished"] is True
    # 已送出後不可再改選項。
    assert invoke(
        posting,
        "save_publish_draft",
        {
            "brand_id": posting.brand_id,
            "post_id": post["id"],
            "version": done["version"],
            "format": "text",
            "caption": done["caption"],
            "platforms": ["facebook", "threads"],
            "facebook_unpublished": False,
        },
    ).isError


def test_facebook_unpublished_retry_details_only_when_facebook_is_sent(posting):
    post = draft(posting, facebook_unpublished=True)
    posting.mock.fail_threads = True
    assert not confirm(posting, post, prepared(posting, post)).isError
    current = ok(posting, "get_publish_post", {"post_id": post["id"]})
    assert current["status"] == "partial" and current["facebook_unpublished"] is True
    posting.mock.requests.clear()
    posting.mock.fail_threads = False
    prep = ok(
        posting, "retry_failed_platforms", {"post_id": post["id"], "version": current["version"]}
    )
    # 重試只送 Threads，Facebook 不會再送，明細不應宣稱 Facebook 會以未發佈貼文建立。
    assert set(prep["details"]["accounts"]) == {"threads"}
    assert prep["details"]["facebook_unpublished"] is False
    assert not confirm(posting, current, prep).isError
    assert not facebook_requests(posting.mock)


def test_facebook_unpublished_tool_descriptions_state_the_scope():
    specs = agent_tools.PUBLISH_SPECS
    save = specs["save_publish_draft"][2]
    assert "facebook_unpublished" in save and "只影響Facebook" in save
    assert "存成草稿不發佈" in save
    assert "facebook_unpublished" in specs["get_publish_post"][2]
    assert "facebook_unpublished" in specs["prepare_publish"][2]
    schema = {t.name: t for t in agent_tools.list_tools()}["save_publish_draft"].inputSchema
    assert "facebook_unpublished" in schema["properties"]


# ---- composer1：平台選項、分段與確認指紋 ----


def update_draft_options(client, post, **changes):
    return invoke(
        client,
        "save_publish_draft",
        {
            "brand_id": client.brand_id,
            "post_id": post["id"],
            "version": post["version"],
            "format": post["format"],
            "caption": post["caption"],
            "platforms": post["platforms"],
            **changes,
        },
    )


def test_agent_platform_options_read_write_merge_and_custom_segments(posting):
    post = draft(
        posting,
        platform_options={
            "facebook": {"video_format": "feed"},
            "instagram": {"share_to_feed": False},
            "threads": {"segments": ["手動第一段", "手動第二段"], "segments_custom": True},
        },
    )
    original = post["platform_options"]
    kept = update_draft_options(posting, post, caption="改過的共用文案")
    assert not kept.isError and kept.structuredContent["platform_options"] == original
    shown = ok(posting, "get_publish_post", {"post_id": post["id"]})
    assert shown["platform_options"] == original
    listed = ok(posting, "list_publish_posts", {"brand_id": posting.brand_id})
    assert listed["items"][0]["platform_options"] == original
    reset = update_draft_options(
        posting, kept.structuredContent, platform_options={"threads": {"segments_custom": False}}
    )
    assert not reset.isError
    assert reset.structuredContent["platform_options"]["threads"] == {
        "segments": ["改過的共用文案"],
        "segments_custom": False,
    }
    assert reset.structuredContent["platform_options"]["instagram"]["share_to_feed"] is False
    options = ok(posting, "get_publish_options", {"brand_id": posting.brand_id})
    assert options["rules"]["instagram"]["mentions"] == 20


@pytest.mark.parametrize(
    "platform,values",
    [
        ("facebook", {"video_format": "feed"}),
        ("instagram", {"share_to_feed": False}),
        ("threads", {"segments": ["改過的第一段", "第二段"], "segments_custom": True}),
    ],
)
def test_platform_options_and_segments_invalidate_agent_fingerprint_without_version_change(
    posting, platform, values
):
    post = draft(posting, platform_options={"threads": {"segments": ["第一段", "第二段"]}})
    prep = prepared(posting, post)
    assert prep["details"]["platform_options"] == post["platform_options"]
    assert prep["details"]["threads_segments"] == ["第一段", "第二段"]
    with posting.app.state.session_factory.begin() as session:
        options = dict(post["platform_options"])
        options[platform] = values
        session.execute(
            update(PublishPost)
            .where(PublishPost.id == post["id"])
            .values(platform_options_json=options)
        )
    result = confirm(posting, post, prep)
    assert result.isError and "重新 prepare_publish" in result.content[0].text
    assert posting.mock.requests == []


def test_agent_custom_segments_obey_brand_forbidden_phrases(posting):
    from app.services.branding import put_setting

    with posting.app.state.session_factory.begin() as session:
        put_setting(session, f"brand.rules.{posting.brand_id}", {"forbidden_phrases": ["保證達成"]})
    result = invoke(
        posting,
        "save_publish_draft",
        {
            "brand_id": posting.brand_id,
            "format": "text",
            "caption": "正常文案",
            "platforms": ["threads"],
            "platform_options": {"threads": {"segments": ["保證達成"]}},
        },
    )
    assert result.isError and "segments" in result.content[0].text
    assert posting.mock.requests == []


def test_agent_chain_confirmation_and_results_hide_raw_platform_ids(posting):
    post = draft(
        posting,
        platforms=["threads"],
        platform_options={"threads": {"segments": ["第一段", "第二段"]}},
    )
    prep = prepared(posting, post)
    assert prep["details"]["threads_segments"] == ["第一段", "第二段"]
    assert not confirm(posting, post, prep).isError
    shown = ok(posting, "get_publish_post", {"post_id": post["id"]})
    assert shown["status"] == "done"
    assert shown["targets"][0]["detail"] == {
        "successful_segments": 2,
        "total_segments": 2,
        "failed_segment": None,
    }
    assert "segment_ids" not in json.dumps(shown) and "platform_post_id" not in json.dumps(shown)
    listing = ok(posting, "list_publish_posts", {"brand_id": posting.brand_id})
    assert listing["items"][0]["targets"] == shown["targets"]


def test_composer_tool_descriptions_and_schema_explain_no_numbering():
    save = agent_tools.PUBLISH_SPECS["save_publish_draft"][2]
    assert "platform_options" in save and "Threads分段不加編號" in save and "沿用原值" in save
    assert "Threads分段全文" in agent_tools.PUBLISH_SPECS["prepare_publish"][2]
    assert "失敗段接續" in agent_tools.PUBLISH_SPECS["retry_failed_platforms"][2]
    schema = agent_tools.PUBLISH_SPECS["save_publish_draft"][0].model_json_schema()
    assert "platform_options" in schema["properties"]


def test_agent_story_draft_order_confirm_fingerprint_and_metrics(posting):
    from app.models import PublishMedia
    from app.services import publish_story_insights

    post = draft(posting, format="story", caption="", platforms=["facebook", "instagram"])
    factory = posting.app.state.session_factory
    for index in range(2):
        link = ok(
            posting, "create_upload_link", {"post_id": post["id"], "filename": f"story-{index}.jpg"}
        )
        assert (
            posting.put(
                urlsplit(link["upload_url"]).path, content=jpeg_bytes(1080, 1920)
            ).status_code
            == 200
        )
    post = ok(posting, "get_publish_post", {"post_id": post["id"]})
    prep = prepared(posting, post)
    assert prep["details"]["format"] == "story" and prep["details"]["story_count"] == 2
    assert set(prep["details"]["accounts"]) == {"facebook", "instagram"}
    assert not posting.mock.calls
    with factory.begin() as session:
        media = list(
            session.scalars(select(PublishMedia).where(PublishMedia.post_id == post["id"]))
        )
        media[0].sha256 = "f" * 64
    assert confirm(posting, post, prep).isError and not posting.mock.calls
    prep = prepared(posting, post)
    assert not confirm(posting, post, prep).isError
    assert confirm(posting, post, prep).isError
    with factory.begin() as session:
        target = next(t for t in publish.targets(session, post["id"]) if t.platform == "instagram")
        publish_story_insights.store(session, target.id, 1, utc_now(), {"views": 120}, final=True)
    result = ok(posting, "get_publish_post", {"post_id": post["id"]})
    ig = next(t for t in result["targets"] if t["platform"] == "instagram")
    assert ig["detail"]["successful_stories"] == 2
    assert ig["stories"][0]["metrics"]["views"] == 120
    assert "platform_post_id" not in json.dumps(ig)
    listed = ok(posting, "list_publish_posts", {"brand_id": posting.brand_id})
    assert listed["items"][0]["format"] == "story"
    assert "platform_post_id" not in json.dumps(listed)
    assert invoke(
        posting,
        "save_publish_draft",
        {
            "brand_id": posting.brand_id,
            "format": "story",
            "caption": "不能帶文字",
            "platforms": ["instagram"],
        },
    ).isError


def test_agent_story_media_reordering_invalidates_confirmation(posting):
    post = draft(posting, format="story", caption="", platforms=["instagram"])
    for index in range(2):
        link = ok(
            posting, "create_upload_link", {"post_id": post["id"], "filename": f"story-{index}.jpg"}
        )
        assert (
            posting.put(
                urlsplit(link["upload_url"]).path, content=jpeg_bytes(1080, 1920)
            ).status_code
            == 200
        )
    post = ok(posting, "get_publish_post", {"post_id": post["id"]})
    prep = prepared(posting, post)
    order = [m["id"] for m in reversed(post["media"])]
    changed = ok(
        posting,
        "save_publish_draft",
        {
            "brand_id": posting.brand_id,
            "post_id": post["id"],
            "version": post["version"],
            "format": "story",
            "platforms": ["instagram"],
            "media_ids": order,
        },
    )
    assert [m["id"] for m in changed["media"]] == order
    assert confirm(posting, changed, prep).isError and not posting.mock.calls


# ---- ytpublish：YouTube 選項、縮圖、明細與確認指紋 ----


def youtube_ready(client):
    with client.app.state.session_factory.begin() as session:
        seed_youtube(session, client.app.state.settings, client.brand_id)


def attach(client, post, content, filename="clip.mp4", role=None):
    args = {"post_id": post["id"], "filename": filename, **({"role": role} if role else {})}
    link = ok(client, "create_upload_link", args)
    response = client.put(urlsplit(link["upload_url"]).path, content=content)
    assert response.status_code == 200, response.text


def youtube_post(client, **changes):
    youtube_ready(client)
    options = {"youtube": {"title": "MCP 自訂標題", "privacy": "unlisted", "made_for_kids": True}}
    post = draft(
        client,
        format="video",
        caption="MCP 標題\n\nMCP 說明 #標籤",
        platforms=["youtube"],
        platform_options=options,
        **changes,
    )
    attach(client, post, video_bytes(1920, 1080))
    attach(client, post, jpeg_bytes(1280, 720), "thumb.jpg", role="thumbnail")
    return ok(client, "get_publish_post", {"post_id": post["id"]})


def test_agent_youtube_options_thumbnail_details_and_publish(posting):
    post = youtube_post(posting)
    assert post["platform_options"]["youtube"]["title"] == "MCP 自訂標題"
    assert post["platform_options"]["youtube"]["privacy"] == "unlisted"
    # 縮圖不是發佈素材：素材清單只有影片，縮圖另列且不含路徑。
    assert len(post["media"]) == 1 and post["thumbnail"]["name"] == "thumb.jpg"
    assert "relative_path" not in json.dumps(post)
    assert post["checks"]["youtube"]["ok"]
    options = ok(posting, "get_publish_options", {"brand_id": posting.brand_id})
    assert options["platforms"]["youtube"]["ready"]
    rule = options["rules"]["youtube"]
    assert (rule["title"], rule["caption"], rule["text_supported"]) == (100, 5000, False)
    assert rule["thumbnail"]["bytes"] == 2 * 1024**2
    assert rule["thumbnail"]["shorts_supported"] is False
    prep = prepared(posting, post)
    assert not posting.mock.calls
    assert prep["details"]["youtube"] == {
        "title": "MCP 自訂標題",
        "privacy": "unlisted",
        "made_for_kids": True,
        "has_thumbnail": True,
        "shorts": False,
    }
    assert set(prep["details"]["accounts"]) == {"youtube"}
    assert not confirm(posting, post, prep).isError
    google = posting.mock.youtube
    assert len(google.completed) == 1
    metadata = google.sessions["mockupload1"]["metadata"]
    assert metadata["snippet"]["title"] == "MCP 自訂標題"
    assert metadata["status"] == {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": True}
    result = ok(posting, "get_publish_post", {"post_id": post["id"]})
    target = result["targets"][0]
    assert target["status"] == "succeeded"
    assert target["detail"] == {"privacy_status": "unlisted", "thumbnail": {"status": "applied"}}
    # 平台影片編號與上傳工作階段不對 MCP 暴露。
    serial = json.dumps(ok(posting, "list_publish_posts", {"brand_id": posting.brand_id}))
    assert "platform_post_id" not in json.dumps(result) and "mockupload" not in serial
    assert "video_id" not in json.dumps(result)


@pytest.mark.parametrize("change", ["title", "privacy", "kids", "thumbnail", "caption"])
def test_youtube_options_and_thumbnail_invalidate_agent_fingerprint(posting, change):
    from app.models import PublishMedia

    post = youtube_post(posting)
    prep = prepared(posting, post)
    with posting.app.state.session_factory.begin() as session:
        row = session.get(PublishPost, post["id"])
        options = {**row.platform_options_json}
        if change == "thumbnail":
            thumbnail = session.scalar(
                select(PublishMedia).where(
                    PublishMedia.post_id == post["id"], PublishMedia.role == "thumbnail"
                )
            )
            thumbnail.sha256 = "f" * 64
        elif change == "caption":
            session.execute(
                update(PublishPost)
                .where(PublishPost.id == post["id"])
                .values(captions_json={"youtube": "另寫的 YouTube 說明"})
            )
        else:
            key, value = {
                "title": ("title", "改過的標題"),
                "privacy": ("privacy", "private"),
                "kids": ("made_for_kids", False),
            }[change]
            changed = {**options, "youtube": {**options["youtube"], key: value}}
            session.execute(
                update(PublishPost)
                .where(PublishPost.id == post["id"])
                .values(platform_options_json=changed)
            )
    result = confirm(posting, post, prep)
    assert result.isError and "重新 prepare_publish" in result.content[0].text
    assert not posting.mock.calls


def test_youtube_thumbnail_failure_is_reported_through_mcp(posting):
    posting.mock.youtube.thumbnail_error = (403, "forbidden")
    post = youtube_post(posting)
    prep = prepared(posting, post)
    assert not confirm(posting, post, prep).isError
    result = ok(posting, "get_publish_post", {"post_id": post["id"]})
    target = result["targets"][0]
    assert result["status"] == "done" and target["status"] == "succeeded"
    thumbnail = target["detail"]["thumbnail"]
    assert thumbnail["status"] == "failed" and thumbnail["code"] == "forbidden"
    assert "電話驗證" in thumbnail["reason"]
    assert len(posting.mock.youtube.completed) == 1


def test_youtube_title_obeys_brand_forbidden_phrases(posting):
    from app.services.branding import put_setting

    youtube_ready(posting)
    with posting.app.state.session_factory.begin() as session:
        put_setting(session, f"brand.rules.{posting.brand_id}", {"forbidden_phrases": ["保證達成"]})
    result = invoke(
        posting,
        "save_publish_draft",
        {
            "brand_id": posting.brand_id,
            "format": "video",
            "caption": "正常文案",
            "platforms": ["youtube"],
            "platform_options": {"youtube": {"title": "保證達成的標題"}},
        },
    )
    assert result.isError and "youtube_title" in result.content[0].text
    assert not posting.mock.calls


def test_agent_youtube_rejects_non_video_and_bad_options(posting):
    youtube_ready(posting)
    post = draft(posting, format="text", platforms=["youtube"])
    assert not ok(posting, "get_publish_post", {"post_id": post["id"]})["checks"]["youtube"]["ok"]
    error = invoke(posting, "prepare_publish", {"post_id": post["id"], "version": post["version"]})
    assert error.isError and "YouTube 只支援影片" in error.content[0].text
    for options in (
        {"youtube": {"privacy": "friends"}},
        {"youtube": {"made_for_kids": "yes"}},
        {"youtube": {"thumbnail_media_id": 1}},
        {"youtube": {"category": "10"}},
    ):
        assert invoke(
            posting,
            "save_publish_draft",
            {
                "brand_id": posting.brand_id,
                "format": "video",
                "caption": "標題",
                "platforms": ["youtube"],
                "platform_options": options,
            },
        ).isError
    assert not posting.mock.calls


def test_agent_thumbnail_upload_needs_a_video_draft_and_jpeg_png(posting):
    youtube_ready(posting)
    image = draft(posting, format="image", platforms=["youtube"])
    link = ok(
        posting,
        "create_upload_link",
        {"post_id": image["id"], "filename": "t.jpg", "role": "thumbnail"},
    )
    refused = posting.put(urlsplit(link["upload_url"]).path, content=jpeg_bytes(1280, 720))
    assert refused.status_code == 422 and "影片" in refused.text
    video = draft(posting, format="video", platforms=["youtube"])
    link = ok(
        posting,
        "create_upload_link",
        {"post_id": video["id"], "filename": "t.mp4", "role": "thumbnail"},
    )
    refused = posting.put(urlsplit(link["upload_url"]).path, content=video_bytes())
    assert refused.status_code == 422
    assert invoke(
        posting, "create_upload_link", {"post_id": video["id"], "filename": "t.jpg", "role": "x"}
    ).isError
    assert not ok(posting, "get_publish_post", {"post_id": video["id"]})["media"]


def test_youtube_tool_descriptions_state_the_options():
    specs = agent_tools.PUBLISH_SPECS
    save = specs["save_publish_draft"][2]
    for text in ("youtube.title", "youtube.privacy", "youtube.made_for_kids", "role=thumbnail"):
        assert text in save
    upload = specs["create_upload_link"][2]
    assert "role" in upload and "thumbnail" in upload
    assert "youtube" in specs["prepare_publish"][2] and "縮圖" in specs["prepare_publish"][2]
    assert "thumbnail" in specs["get_publish_post"][2]
    schema = {t.name: t for t in agent_tools.list_tools()}
    assert "role" in schema["create_upload_link"].inputSchema["properties"]


def test_agent_long_threads_caption_is_not_split_and_reports_overflow_position(posting):
    # MCP 代理存超過 500 字的 Threads 文案：不自動拆段，準備發佈時指出從第幾個字開始超出。
    caption = "甲" * 500 + "乙丙"
    post = draft(posting, caption=caption, platforms=["threads"])
    assert post["platform_options"]["threads"] == {"segments": [caption], "segments_custom": False}
    result = invoke(
        posting, "prepare_publish", {"post_id": post["id"], "version": post["version"]}
    )
    text = result.content[0].text
    assert result.isError and "Threads 文案超過 500 字上限" in text, text
    assert "從第 501 個字「乙丙」開始超出" in text, text


# ---- Instagram Reels 封面：上傳用途、明細與確認指紋 ----


def test_agent_instagram_cover_details_and_fingerprint(posting):
    from app.models import PublishMedia

    post = draft(posting, format="video", caption="MCP Reels", platforms=["instagram"])
    attach(posting, post, video_bytes())
    attach(posting, post, jpeg_bytes(1080, 1920), "cover.jpg", role="cover")
    post = ok(posting, "get_publish_post", {"post_id": post["id"]})
    # 封面不是發佈素材：素材清單只有影片，封面另列且不含路徑。
    assert len(post["media"]) == 1 and post["cover"]["name"] == "cover.jpg"
    assert post["checks"]["instagram"]["ok"]
    prep = prepared(posting, post)
    assert prep["details"]["instagram"] == {"has_cover": True}
    assert prep["details"]["youtube"] is None
    with posting.app.state.session_factory.begin() as session:
        cover = session.scalar(
            select(PublishMedia).where(
                PublishMedia.post_id == post["id"], PublishMedia.role == "cover"
            )
        )
        cover.sha256 = "f" * 64
    # 換了封面內容，舊確認碼失效，不會呼叫平台。
    assert confirm(posting, post, prep).isError and not posting.mock.calls


def test_agent_facebook_cover_details_and_fingerprint(posting):
    from app.models import PublishMedia

    post = draft(posting, format="video", caption="MCP FB", platforms=["facebook"])
    attach(posting, post, video_bytes())
    attach(posting, post, jpeg_bytes(1080, 1920), "fb.jpg", role="fb_cover")
    post = ok(posting, "get_publish_post", {"post_id": post["id"]})
    assert len(post["media"]) == 1 and post["facebook_cover"]["name"] == "fb.jpg"
    prep = prepared(posting, post)
    assert prep["details"]["facebook"] == {"has_cover": True}
    assert prep["details"]["instagram"] is None
    with posting.app.state.session_factory.begin() as session:
        cover = session.scalar(
            select(PublishMedia).where(
                PublishMedia.post_id == post["id"], PublishMedia.role == "fb_cover"
            )
        )
        cover.sha256 = "e" * 64
    assert confirm(posting, post, prep).isError and not posting.mock.calls


BRAND_CAPTION = (
    "預約請撥 0912-345-678 或寫信 hello@example.test，追蹤 @isolated.brand，"
    "門市在台中市西屯區台灣大道三段99號，網址 https://example.test/home/shop"
)


def test_brand_caption_contact_details_pass_get_prepare_and_confirm_unchanged(posting):
    segments = ["第一段 @isolated.brand", "第二段 0912-345-678"]
    post = draft(
        posting,
        caption=BRAND_CAPTION,
        platform_captions={"facebook": "FB 版 @isolated.brand hello@example.test"},
        platform_options={"threads": {"segments": segments, "segments_custom": True}},
    )
    assert post["caption"] == BRAND_CAPTION
    shown = ok(posting, "get_publish_post", {"post_id": post["id"]})
    assert shown["caption"] == BRAND_CAPTION
    assert shown["captions"]["facebook"] == "FB 版 @isolated.brand hello@example.test"
    assert shown["platform_options"]["threads"]["segments"] == segments
    listed = ok(posting, "list_publish_posts", {"brand_id": posting.brand_id})["items"][0]
    assert listed["caption"] == BRAND_CAPTION[:60]
    prep = prepared(posting, shown)
    assert prep["details"]["caption"] == BRAND_CAPTION
    assert prep["details"]["threads_segments"] == segments
    assert not confirm(posting, shown, prep).isError
    # 秘密樣式仍過濾，且被過濾的明細不能確認。
    secret = draft(posting, caption="內部 token=abc123secret 不該外流")
    assert "abc123secret" not in ok(posting, "get_publish_post", {"post_id": secret["id"]})[
        "caption"
    ]
    secret = {"post_id": secret["id"], "version": secret["version"]}
    result = invoke(posting, "prepare_publish", secret)
    assert result.isError and "需遮蔽或過長" in result.content[0].text
    # 回應大小限制照舊：過長文案在 prepare 被拒。
    long = draft(posting, platforms=["facebook"], caption="長" * 56_000)
    result = invoke(posting, "prepare_publish", {"post_id": long["id"], "version": long["version"]})
    assert result.isError and "需遮蔽或過長" in result.content[0].text


@pytest.mark.parametrize(
    "changes",
    [
        {"caption": "請撥 [REDACTED_PHONE] 預約"},
        {"caption": "追蹤 [觀眾帳號]"},
        {"platform_captions": {"facebook": "感謝 [觀眾] 支持"}},
        {"platform_options": {"threads": {"segments": ["[已遮蔽]"], "segments_custom": True}}},
    ],
)
def test_save_publish_draft_rejects_projection_placeholders(posting, changes):
    post = draft(posting, caption=BRAND_CAPTION)
    result = invoke(
        posting,
        "save_publish_draft",
        {
            "brand_id": posting.brand_id,
            "post_id": post["id"],
            "version": post["version"],
            "format": "text",
            "caption": BRAND_CAPTION,
            "platforms": ["facebook", "threads"],
            **changes,
        },
    )
    assert result.isError and "文案含遮蔽佔位字串，請提供原文" in result.content[0].text
    with posting.app.state.session_factory() as session:
        row = session.get(PublishPost, post["id"])
        assert row.caption == BRAND_CAPTION and row.version == post["version"]


def real_image(width, height, kind="JPEG"):
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 80, 40)).save(buffer, kind)
    return buffer.getvalue()


def preview_sizes(result):
    import base64
    import io

    from mcp import types
    from PIL import Image

    sizes = []
    for item in result.content[1:]:
        assert isinstance(item, types.ImageContent) and item.mimeType == "image/jpeg"
        with Image.open(io.BytesIO(base64.b64decode(item.data))) as image:
            assert image.format == "JPEG"
            sizes.append(image.size)
    return sizes


def test_get_publish_post_attaches_image_previews(posting):
    post = draft(posting, format="image", platforms=["facebook"])
    attach(posting, post, real_image(1600, 1200), "photo.jpg")
    result = invoke(posting, "get_publish_post", {"post_id": post["id"]}, "viewer")
    assert not result.isError and result.content[0].type == "text"
    # 影像只在 content，structuredContent 與文字 JSON 維持原樣、不含 base64。
    assert preview_sizes(result) == [(480, 360)]
    assert json.loads(result.content[0].text) == result.structuredContent
    assert "data" not in json.dumps(result.structuredContent["media"])

    carousel = draft(posting, format="carousel", platforms=["facebook"])
    for index in range(agent_publish.PREVIEW_LIMIT + 1):
        attach(posting, carousel, real_image(800, 1000, "PNG"), f"slide{index}.png")
    result = invoke(posting, "get_publish_post", {"post_id": carousel["id"]})
    assert len(result.structuredContent["media"]) == agent_publish.PREVIEW_LIMIT + 1
    assert preview_sizes(result) == [(384, 480)] * agent_publish.PREVIEW_LIMIT


def test_get_publish_post_without_images_returns_text_only(posting):
    text = draft(posting)
    video = draft(posting, format="video", platforms=["facebook"])
    attach(posting, video, video_bytes())
    broken = draft(posting, format="image", platforms=["facebook"])
    attach(posting, broken, jpeg_bytes(), "broken.jpg")
    for post in (text, video, broken):
        result = invoke(posting, "get_publish_post", {"post_id": post["id"]})
        assert not result.isError and [item.type for item in result.content] == ["text"]


def test_get_publish_post_previews_never_cross_brands(posting):
    post = draft(posting, format="image", platforms=["facebook"])
    attach(posting, post, real_image(1200, 1200), "photo.jpg")
    with posting.app.state.session_factory.begin() as session:
        session.get(PublishPost, post["id"]).brand_id = posting.hidden_brand
    result = invoke(posting, "get_publish_post", {"post_id": post["id"]}, "marketing")
    assert result.isError and [item.type for item in result.content] == ["text"]
    assert "找不到" in result.content[0].text
