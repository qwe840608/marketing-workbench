"""Ingress security, durable ACK, baseline DB equivalence and scheduler leases."""

import base64
import hashlib
import hmac
import json
import time
from datetime import timedelta
from types import SimpleNamespace

import pytest
from message_fixtures import send_data as send_data
from pydantic import SecretStr
from sqlalchemy import func, select
from test_gateway_oracle import NORMAL

from app.models import (
    Account,
    AuditLog,
    Brand,
    CommentPoll,
    Contact,
    InboundJob,
    Message,
    RawEvent,
    Setting,
    Thread,
    WebhookFailure,
)
from app.models.base import utc_now
from app.services import ingest
from app.services.gateway_workers import Workers
from app.services.scheduler import INTERVALS, Scheduler
from app.services.webhook_normalize import dump, verify_control, verify_signature

KEY = "isolated-fixture-key-" + "x" * 32
BOT = "U" + "a" * 32
PEER = "U" + "b" * 32


@pytest.fixture
def gateway(client, settings, monkeypatch):
    settings.line_channel_secret = SecretStr(KEY)
    settings.meta_app_secret = SecretStr(KEY)
    settings.meta_page_id = "111111"
    settings.meta_ig_account_id = "222222"
    settings.meta_verify_token = SecretStr(KEY)
    settings.webhook_probe_secret = SecretStr(KEY)
    settings.notify_line_channel_secret = SecretStr(KEY)
    settings.notify_line_bot_user_id = BOT
    monkeypatch.setattr(
        Workers,
        "http",
        lambda *a, **k: {"statusCode": 200, "body": {"userId": PEER, "displayName": "測試用戶"}},
    )
    factory = client.app.state.session_factory
    with factory.begin() as session:
        brand = Brand(slug="isolated-gateway", name="隔離品牌")
        session.add(brand)
        session.flush()
        for platform, identity in [("line", BOT), ("facebook", "111111"), ("instagram", "222222")]:
            session.add(
                Account(
                    brand_id=brand.id,
                    platform=platform,
                    external_id=identity,
                    name="隔離帳號",
                    status="disconnected",
                )
            )
    return client, settings, factory


def sign(raw, platform="line"):
    value = hmac.digest(KEY.encode(), raw, "sha256")
    return (
        {"x-hub-signature-256": "sha256=" + value.hex()}
        if platform == "meta"
        else {"x-line-signature": base64.b64encode(value).decode()}
    )


def line_payload():
    return {
        "destination": BOT,
        "events": [
            {
                "type": "message",
                "webhookEventId": "fixture-event-1",
                "timestamp": 1790380800000,
                "source": {"type": "user", "userId": PEER},
                "message": {
                    "id": "fixture-message-1",
                    "type": "text",
                    "text": "[測試] 中文\n與 emoji 🧹",
                },
                "deliveryContext": {"isRedelivery": True},
            }
        ],
    }


@pytest.mark.parametrize("platform", ["line", "meta"])
@pytest.mark.parametrize("bad", [None, [], {}, "", "bad", "0" * 64])
def test_signatures_reject_wrong_type_format_and_value(platform, bad):
    assert not verify_signature(b"{}", bad, KEY, platform)


@pytest.mark.parametrize("platform", ["line", "meta"])
def test_signatures_are_raw_bytes_not_reformatted_json(platform):
    raw = '{"text":"中文\n🧹"}'.encode()
    headers = sign(raw, platform)
    signature = next(iter(headers.values()))
    assert verify_signature(raw, signature, KEY, platform)
    assert not verify_signature(raw + b" ", signature, KEY, platform)


@pytest.mark.parametrize("offset", [-120, 120, 0])
def test_probe_path_key_expiry_and_future(offset):
    stamp = str(int(time.time()) + offset)
    path = "/webhook/mwb-gateway-probe"
    signature = hmac.new(KEY.encode(), f"GET\n{path}\n{stamp}".encode(), hashlib.sha256).hexdigest()
    headers = {"x-mwb-probe-time": stamp, "x-mwb-probe-signature": signature}
    assert verify_control(headers, KEY, path) == (offset == 0)
    assert not verify_control(headers, KEY + "wrong", path)
    assert not verify_control(headers, KEY, "/webhook/meta-sync")


@pytest.mark.parametrize("stamp", [None, [], "0", "not-a-time", "1790000000\n"])
def test_probe_invalid_timestamp(stamp):
    assert not verify_control(
        {"x-mwb-probe-time": stamp, "x-mwb-probe-signature": "0" * 64},
        KEY,
        "/webhook/mwb-gateway-probe",
    )


def test_webhook_commit_redelivery_profile_and_idempotency(gateway):
    client, _, factory = gateway
    for payload in (line_payload(), {"events": [{"type": "message"}]}, {"events": []}):
        raw = dump(payload).encode()
        for _ in range(2):
            assert (
                client.post("/webhook/line-inbound", content=raw, headers=sign(raw)).status_code
                == 200
            )
    with factory() as session:
        for model in (Message, RawEvent, Contact, Thread, InboundJob):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        assert (
            session.scalar(select(Account.send_enabled).where(Account.platform == "line")) is False
        )


def test_invalid_message_persists_raw_and_does_not_ack(gateway):
    client, _, factory = gateway
    for payload in (line_payload(), {"events": [{"type": "message"}]}, {"events": []}):
        raw = dump(payload).encode()
        for _ in range(2):
            assert (
                client.post("/webhook/line-inbound", content=raw, headers=sign(raw)).status_code
                == 200
            )
    with factory() as session:
        for model in (Message, RawEvent, Contact, Thread, InboundJob):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        assert (
            session.scalar(select(Account.send_enabled).where(Account.platform == "line")) is False
        )


def test_empty_events_and_unknown_account(gateway):
    client, _, factory = gateway
    for payload, status in [
        ({"destination": BOT, "events": []}, 200),
        ({"destination": PEER, "events": []}, 200),
    ]:
        raw = dump(payload).encode()
        assert (
            client.post("/webhook/line-inbound", content=raw, headers=sign(raw)).status_code
            == status
        )
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(RawEvent)) == 0


@pytest.mark.parametrize("name", ["line-inbound", "meta-inbound", "line-notify"])
def test_signature_failure_count_only_platform(gateway, name):
    client, _, factory = gateway
    assert (
        client.post("/webhook/" + name, content=b'{"private":"never persist"}').status_code == 401
    )
    with factory() as s:
        assert s.scalar(select(WebhookFailure)).count == 1
        assert s.scalar(select(func.count()).select_from(RawEvent)) == 0


def test_notify_group_and_meta_challenge(gateway):
    client, _, factory = gateway
    query = {"hub.mode": "subscribe", "hub.verify_token": KEY, "hub.challenge": "123456"}
    r = client.get("/webhook/meta-inbound", params=query)
    assert (
        r.status_code == 200
        and r.text == "123456"
        and r.headers["content-type"].startswith("text/plain")
    )
    for change in [
        {"hub.mode": "other"},
        {"hub.verify_token": "wrong"},
        {"hub.challenge": "<script>"},
    ]:
        assert client.get("/webhook/meta-inbound", params={**query, **change}).status_code == 403
    raw = dump(
        {
            "destination": BOT,
            "events": [{"type": "join", "source": {"type": "group", "groupId": "C" + "a" * 32}}],
        }
    ).encode()
    r = client.post("/webhook/line-notify", content=raw, headers=sign(raw))
    assert r.json() == {"ok": True}
    with factory() as s:
        assert (
            "C" + "a" * 32
            in s.scalar(
                select(Setting).where(Setting.key == "notification.discovered_groups")
            ).value_json
        )


BLOCKED = [
    "/",
    "/signin",
    "/setup",
    "/home/workflows",
    "/workflow/test",
    "/rest/workflows",
    "/rest/settings",
    "/api/health",
    "/webhook-test/mwb-gateway-probe",
    "/webhook",
    "/webhook/",
    "/Webhook/mwb-gateway-probe",
    "/webhook/../rest/settings",
    "/webhook/%2e%2e/rest/settings",
    "/webhook/%252e%252e/rest/settings",
    "/webhook/test%2f..%2f..%2frest/settings",
]


@pytest.mark.parametrize("path", BLOCKED)
@pytest.mark.parametrize(
    "header",
    [
        {"x-mwb-public": "0"},
        {"x-forwarded-host": "example.ngrok.app"},
        {"x-forwarded-for": "203.0.113.2"},
    ],
)
def test_public_paths_rejected_even_with_internal_host(client, path, header):
    assert client.get(path, headers=header).status_code == 404


def test_public_probe_and_internal_api_remain_separate(gateway):
    client, _, _ = gateway
    stamp = str(int(time.time()))
    path = "/webhook/mwb-gateway-probe"
    signature = hmac.new(KEY.encode(), f"GET\n{path}\n{stamp}".encode(), hashlib.sha256).hexdigest()
    headers = {
        "x-mwb-public": "1",
        "x-mwb-probe-time": stamp,
        "x-mwb-probe-signature": signature,
    }
    assert client.get(path, headers=headers).json() == {
        "ok": True,
        "service": "backend",
        "purpose": "tunnel-check",
    }
    assert client.get(path, headers={"x-mwb-public": "1"}).status_code == 401
    assert (
        client.get(path, headers={**headers, "x-mwb-probe-signature": "0" * 64}).status_code == 401
    )
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/scheduler/status").status_code == 401


def test_sync_signature_binds_body_and_keeps_heavy_work_out_of_response(gateway, monkeypatch):
    client, _, _ = gateway
    from app.services import scheduler

    queued = []
    monkeypatch.setattr(
        scheduler,
        "scheduler_for",
        lambda _: SimpleNamespace(healthy=lambda: True, request=lambda *args: queued.append(args)),
    )
    path = "/webhook/meta-comments-sync"
    raw = b'{"requested_only":true,"post_id":1}'
    stamp = str(int(time.time()))
    material = "POST\n" + path + "\n" + stamp + "\n" + hashlib.sha256(raw).hexdigest()
    signature = hmac.new(KEY.encode(), material.encode(), hashlib.sha256).hexdigest()
    headers = {"x-mwb-sync-time": stamp, "x-mwb-sync-signature": signature}
    assert client.post(path, content=raw.replace(b":1", b":2"), headers=headers).status_code == 401
    assert client.post(path, content=raw, headers=headers).status_code == 200
    assert queued == [("comments", {"requested_only": True, "post_id": 1})]


def test_scheduler_lease_restart_disable_and_results(gateway, monkeypatch):
    _, settings, factory = gateway
    first = Scheduler(factory, settings)
    second = Scheduler(factory, settings)
    now = utc_now()
    assert (
        set(INTERVALS) == {"classify", "notify", "comments", "metrics", "ideation", "publish"}
        and INTERVALS["metrics"] == 3600
    )
    assert not first.claim("comments", now)
    with factory.begin() as session:
        account = session.scalar(select(Account))
        session.add(
            CommentPoll(
                account_id=account.id,
                resource="isolated-manual",
                manual_requested=True,
                next_poll_at=now,
            )
        )
    assert first.claim("comments", now)
    assert not first.claim("comments", now) and not second.claim("comments", now)
    assert second.claim("comments", now + timedelta(seconds=121))
    monkeypatch.setattr(
        "app.services.gateway_workers.Workers.comments",
        lambda *a, **k: {"ok": True, "completed": 2, "paused": False},
    )
    second.execute("comments")
    with factory() as s:
        row = s.scalar(select(Setting).where(Setting.key == "scheduler.job.comments"))
        assert row.value_json["lease_until"] == 0 and row.value_json["result"]["completed"] == 2
        assert (
            s.scalar(select(AuditLog).where(AuditLog.action == "scheduler.run")).detail_json["job"]
            == "comments"
        )
    with factory.begin() as s:
        s.add(Setting(key="scheduler.enabled.comments", value_json={"enabled": False}))
    second.request("comments")
    assert not second.claim("comments", now + timedelta(hours=1))
    assert "dm" not in INTERVALS
    assert not first.claim("dm", now)


def test_scheduler_independent_jobs_no_overlap_and_heartbeat(gateway, monkeypatch):
    import threading

    _, settings, factory = gateway
    scheduler = Scheduler(factory, settings)
    entered = []
    release = threading.Event()
    started = {name: threading.Event() for name in INTERVALS}

    def execute(name):
        entered.append(name)
        started[name].set()
        release.wait(10)

    monkeypatch.setattr(scheduler, "execute", execute)
    try:
        scheduler.tick()
        # Starting a thread does not guarantee it has run before tick returns.
        assert all(started[name].wait(10) for name in INTERVALS if name != "comments")
        scheduler.tick()
        assert sorted(entered) == sorted(set(INTERVALS) - {"comments"})
        with factory() as s:
            assert (
                s.scalar(select(Setting).where(Setting.key == "scheduler.heartbeat")).value_json[
                    "owner"
                ]
                == scheduler.owner
            )
    finally:
        release.set()
        scheduler.close()


@pytest.mark.parametrize(
    "row", NORMAL, ids=[r["name"] + "-db-" + str(i) for i, r in enumerate(NORMAL)]
)
def test_same_payload_database_matches_baseline(gateway, row, monkeypatch):
    client, settings, factory = gateway
    from app.services.webhook_normalize import meta_envelopes

    payload = json.loads(base64.b64decode(row["raw"]))
    expected = [
        c["request"]["body"] for c in row["calls"] if c["request"]["url"].endswith("/ingest/events")
    ]
    envelopes = (
        []
        if row["name"] == "line-inbound"
        else meta_envelopes(payload, settings.meta_page_id, settings.meta_ig_account_id)
    )
    if row["name"] == "line-inbound" or any("messaging" in e for e in payload.get("entry", [])):
        raw = dump(payload).encode()
        assert (
            client.post(
                "/webhook/" + row["name"],
                content=raw,
                headers=sign(raw, "line" if row["name"] == "line-inbound" else "meta"),
            ).status_code
            == 200
        )
        with factory() as session:
            for model in (Contact, Thread, Message, RawEvent, InboundJob):
                assert session.scalar(select(func.count()).select_from(model)) == 0
        return
    tables = (Contact, Thread, Message, RawEvent, InboundJob)

    def snapshot(session):
        return {
            model.__tablename__: [
                {
                    c.name: getattr(r, c.name)
                    for c in model.__table__.columns
                    if c.name
                    not in (
                        "created_at",
                        "updated_at",
                        "received_at",
                        "processed_at",
                        "next_attempt_at",
                        "available_at",
                        "deadline_at",
                    )
                }
                for r in session.scalars(select(model).order_by(model.id))
            ]
            for model in tables
        }

    # Each branch starts from the exact same isolated DB using a rollback-only connection.
    engine = factory.kw["bind"]
    results = []
    from sqlalchemy.orm import Session

    fixed = utc_now()
    monkeypatch.setattr(ingest, "utc_now", lambda: fixed)
    for rows in (expected, envelopes):
        with engine.connect() as connection:
            transaction = connection.begin()
            with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                for envelope in rows:
                    ingest.events(session, dump(envelope).encode(), settings=settings)
                results.append(snapshot(session))
            transaction.rollback()
    assert results[0] == results[1]


@pytest.mark.parametrize("mode", ["404", "timeout", "wrong-user"])
def test_profile_failure_preserves_message_without_invented_name(gateway, monkeypatch, mode):
    client, _, factory = gateway

    def profile(*a, **k):
        if mode == "timeout":
            raise RuntimeError("private error")
        return {
            "statusCode": 404 if mode == "404" else 200,
            "body": {"userId": BOT, "displayName": "wrong name"},
        }

    monkeypatch.setattr(Workers, "http", profile)
    raw = dump(line_payload()).encode()
    assert client.post("/webhook/line-inbound", content=raw, headers=sign(raw)).status_code == 200
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Message)) == 0
        assert s.scalar(select(Contact)) is None


def test_invalid_event_does_not_discard_other_events(gateway):
    client, _, factory = gateway
    for payload in (line_payload(), {"events": [{"type": "message"}]}, {"events": []}):
        raw = dump(payload).encode()
        for _ in range(2):
            assert (
                client.post("/webhook/line-inbound", content=raw, headers=sign(raw)).status_code
                == 200
            )
    with factory() as session:
        for model in (Message, RawEvent, Contact, Thread, InboundJob):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        assert (
            session.scalar(select(Account.send_enabled).where(Account.platform == "line")) is False
        )


def test_native_classify_and_ideation_use_existing_api_only_services(gateway, monkeypatch):
    from app.services import classify, ideation, scheduler

    _, settings, factory = gateway
    calls = []
    monkeypatch.setattr(
        classify, "dispatch", lambda f, s: calls.append(("classify", f, s)) or {"completed": 3}
    )
    monkeypatch.setattr(ideation, "schedule", lambda f, s: [41, 42])
    monkeypatch.setattr(ideation, "process", lambda f, s, i: calls.append(("ideation", i)))
    assert scheduler.dispatch("classify", factory, settings)["completed"] == 3
    assert scheduler.dispatch("ideation", factory, settings) == {"queued": 2}
    assert calls == [("classify", factory, settings), ("ideation", 41), ("ideation", 42)]


def test_scheduler_requests_persist_across_restart(gateway):
    _, settings, factory = gateway
    first = Scheduler(factory, settings)
    second = Scheduler(factory, settings)
    first.request("metrics", {"requested_only": True, "post_id": 123})
    assert second.claim("metrics")
    with factory() as s:
        row = s.scalar(select(Setting).where(Setting.key == "scheduler.job.metrics"))
        assert row.value_json["active_options"] == {"requested_only": True, "post_id": 123}
        assert row.value_json["owner"] == second.owner


def test_ngrok_policy_retains_raw_path_deny_and_marks_all_upstream_requests():
    from app.config import REPO_ROOT

    policy = json.loads((REPO_ROOT / "config/ngrok-traffic-policy.json").read_text())
    rule = policy["on_http_request"][0]
    assert (
        "req.url.path.matches" in rule["expressions"][0]
        and "req.url.raw_path.matches" in rule["expressions"][0]
    )
    assert rule["actions"] == [{"type": "deny", "config": {"status_code": 404}}]
    marker = policy["on_http_request"][1]
    assert not marker.get("expressions")
    assert marker["actions"][0]["config"]["headers"]["x-mwb-public"] == "1"


def test_real_http_27_checks_and_fast_ack(gateway, monkeypatch, tmp_path):
    import socket
    import subprocess
    import threading

    import httpx
    import uvicorn

    from app.config import REPO_ROOT
    from app.main import create_app

    _, settings, factory = gateway
    settings.allowed_hosts = ["127.0.0.1"]
    app = create_app(settings)

    class PublicIngress:
        async def __call__(self, scope, receive, send):
            if scope["type"] == "http":
                scope = {**scope, "headers": [*scope["headers"], (b"x-mwb-public", b"1")]}
            await app(scope, receive, send)

    server = uvicorn.Server(
        uvicorn.Config(PublicIngress(), host="127.0.0.1", port=0, log_config=None, access_log=False)
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    release = threading.Event()
    started = threading.Event()

    def enrich(*args):
        started.set()
        release.wait(10)

    monkeypatch.setattr(Workers, "http", enrich)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        base = f"http://127.0.0.1:{port}"
        code = (
            "import {checkEndpoint} from './scripts/webhooks.mjs'; "
            "await checkEndpoint(process.argv[1],process.argv[2],true);"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", code, base, KEY],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "27 checks" in result.stdout
        directory = tmp_path / "webhooks"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "webhooks-27-isolated.txt").write_text(result.stdout, encoding="utf-8")
        raw = dump(line_payload()).encode()
        response = httpx.post(
            base + "/webhook/line-inbound",
            content=raw,
            headers=sign(raw),
            timeout=2,
            trust_env=False,
        )
        assert response.status_code == 200 and not started.is_set()
        assert not release.is_set()
        with factory() as session:
            assert session.scalar(select(func.count()).select_from(Message)) == 0
    finally:
        release.set()
        server.should_exit = True
        thread.join(10)
        listener.close()
        assert not thread.is_alive()


def test_scheduler_settings_admin_csrf_version_and_audit(client, send_data, settings):
    from message_fixtures import change

    from app.models import Staff

    view = client.get("/api/scheduler/jobs")
    assert view.status_code == 200 and len(view.json()["jobs"]) == 6
    assert {job["name"] for job in view.json()["jobs"]} == {
        "classify", "notify", "comments", "metrics", "ideation", "publish"
    }
    body = {"enabled": False, "version": 0}
    assert client.put("/api/scheduler/jobs/comments", json=body).status_code == 200
    assert client.put("/api/scheduler/jobs/comments", json=body).status_code == 409
    with client.app.state.session_factory() as session:
        assert session.scalar(
            select(Setting).where(Setting.key == "scheduler.enabled.comments")
        ).value_json == {"enabled": False}
        assert session.scalar(
            select(AuditLog).where(AuditLog.action == "scheduler.settings")
        ).detail_json == {"job": "comments", "enabled": False}
    assert (
        client.put(
            "/api/scheduler/jobs/comments",
            json={"enabled": True, "version": 1},
            headers={"x-csrf-token": "wrong"},
        ).status_code
        == 403
    )
    change(send_data, Staff, "staff", role="marketing")
    assert client.get("/api/scheduler/jobs").status_code == 403
    assert (
        client.put("/api/scheduler/jobs/comments", json={"enabled": True, "version": 1}).status_code
        == 403
    )


def test_missing_transport_credentials_never_call_platform(settings):
    from app.services.gateway_workers import Workers

    # 沒有資料庫工廠：任何 service 呼叫都會在開 session 時失敗，等同舊測試的「後端不得被呼叫」。
    worker = Workers(
        None,
        settings,
        request=lambda *a, **k: pytest.fail("platform must not be called"),
    )
    assert worker.metrics() == {"ok": False, "error": "meta_configuration_missing"}
    assert worker.notifications() == {"ok": False, "error": "notify_configuration_missing"}


@pytest.mark.parametrize("name", ["classify", "notify", "ideation", "meta-dm-backfill"])
def test_schedule_only_jobs_have_no_public_trigger(gateway, name):
    client, _, _ = gateway
    assert client.post("/webhook/" + name, content=b"{}").status_code == 404


def test_later_malformed_meta_entry_keeps_preceding_committed_event(gateway):
    client, settings, factory = gateway
    payload = {
        "object": "page",
        "entry": [
            {
                "id": settings.meta_page_id,
                "time": 1790380800,
                "messaging": [
                    {
                        "sender": {"id": "333333"},
                        "recipient": {"id": settings.meta_page_id},
                        "timestamp": 1790380800000,
                        "message": {"mid": "partial-mid", "text": "隔離訊息"},
                    }
                ],
            },
            {"id": settings.meta_page_id, "messaging": "invalid"},
        ],
    }
    raw = dump(payload).encode()
    assert (
        client.post("/webhook/meta-inbound", content=raw, headers=sign(raw, "meta")).status_code
        == 400
    )
    with factory() as session:
        assert session.scalar(select(Message)) is None
        assert session.scalar(select(RawEvent)) is None


@pytest.mark.parametrize("platform", ["facebook", "instagram"])
def test_mixed_meta_webhook_discards_dm_and_preserves_comment(gateway, platform):
    client, settings, factory = gateway
    facebook = platform == "facebook"
    account = settings.meta_page_id if facebook else settings.meta_ig_account_id
    value = {
        "from": {"id": "333333", "name": "isolated"},
        "created_time": 1790380800,
        **(
            {
                "item": "comment",
                "verb": "add",
                "comment_id": "public-comment",
                "post_id": "public-post",
                "message": "public text",
            }
            if facebook
            else {"id": "public-comment", "media": {"id": "public-post"}, "text": "public text"}
        ),
    }
    raw = dump(
        {
            "object": "page" if facebook else "instagram",
            "entry": [
                {
                    "id": account,
                    "time": 1790380800,
                    "messaging": [
                        {"message": {"mid": "discard-dm", "text": "discard-private-text"}}
                    ],
                    "changes": [{"field": "feed" if facebook else "comments", "value": value}],
                }
            ],
        }
    ).encode()
    for _ in range(2):
        result = client.post("/webhook/meta-inbound", content=raw, headers=sign(raw, "meta"))
        assert result.status_code == 200 and result.json()["events"] == 1
    with factory() as session:
        assert list(session.scalars(select(Message.text))) == ["public text"]
        assert list(session.scalars(select(Thread.kind))) == ["comment_thread"]
        raws = list(session.scalars(select(RawEvent)))
        assert len(raws) == 1 and "discard-private-text" not in json.dumps(raws[0].payload_json)
