"""DM scope, read-only comments and backend-owned monitoring (HTTP mocks only)."""

import hashlib
import hmac
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx
import pytest
from message_fixtures import change
from message_fixtures import send_data as send_data
from pydantic import SecretStr
from sqlalchemy import select
from test_notify import NIGHT, incoming
from test_notify import setup as setup
from test_posts_fix import batch2 as batch2
from test_posts_fix import page_data as page_data
from test_posts_fix import poll_data as poll_data

from app.models import (
    Brand,
    Classification,
    Message,
    Notification,
    Post,
    ReceiveHealthCheck,
    Staff,
    Thread,
)
from app.models.base import utc_now
from app.services import notify
from app.services import receive_health as health


def test_inbox_counts_search_filters_and_dashboard_exclude_comments(client, send_data):
    d = send_data
    with d["factory"].begin() as s:
        t = Thread(
            brand_id=d["brand"],
            account_id=d["account"],
            kind="comment_thread",
            external_id="comment-only",
            stage="booked",
            last_inbound_at=utc_now(),
        )
        s.add(t)
        s.flush()
        m = Message(
            thread_id=t.id,
            external_id="comment",
            direction="in",
            author_type="fan",
            text="only-comment-term",
            sent_at=utc_now(),
        )
        s.add(m)
        s.flush()
        s.add(
            Classification(
                message_id=m.id,
                engine="keyword",
                intent="booking",
                sentiment="neutral",
                sensitive=False,
                action="auto",
                confidence=1,
            )
        )
        s.add(
            Message(
                thread_id=t.id,
                external_id="comment-reply",
                direction="out",
                author_type="brand",
                text="reply",
                sent_at=utc_now(),
            )
        )
        dm = s.get(Message, d["message"])
        dm.sent_at = utc_now() - timedelta(minutes=2)
        s.add(
            Message(
                thread_id=d["thread"],
                external_id="dm-reply",
                direction="out",
                author_type="brand",
                text="reply",
                sent_at=dm.sent_at + timedelta(seconds=60),
            )
        )
    assert client.get("/api/inbox").status_code == 404
    result = client.get("/api/dashboard").json()
    assert result["new_messages"] == 1 and result["new_comments"] == 1
    assert result["top_intent"] is None
    assert (
        not {"stages", "pending_threads", "first_reply_seconds", "first_reply_samples"}
        & result.keys()
    )
    assert result["intents"] == [{"intent": "booking", "count": 1}]


def test_reputation_delivery_links_to_post_and_exact_comment(setup, settings, monkeypatch):
    factory, brand_id, clock = setup
    clock[0] = NIGHT
    thread_id, message_id = incoming(
        setup,
        at=NIGHT,
        kind="comment_thread",
        platform="facebook",
        intent="complaint",
        reputation=0.96,
    )
    with factory.begin() as s:
        t = s.get(Thread, thread_id)
        post = Post(
            account_id=t.account_id,
            external_id="risk-post",
            caption="test",
            media_type="POST",
            published_at=NIGHT,
        )
        s.add(post)
        s.flush()
        t.post_id = post.id
    deliveries = notify.dispatch(factory, settings)
    assert deliveries
    with factory() as s:
        rows = list(
            s.scalars(select(Notification).where(Notification.reason == "public_reputation_risk"))
        )
        assert rows and rows[0].due_at == NIGHT
        text = "\n".join(
            m["text"] for m in notify.compose(s, s.get(Brand, brand_id), rows, settings)
        )
        assert "Facebook" in text and "原生 App" in text and "?view=" not in text
        assert "草稿未就緒" not in text


def test_focus_old_comment_loads_one_page_and_checks_scope(client, page_data):
    with client.app.state.session_factory() as s:
        mid = s.scalar(
            select(Message.id).where(
                Message.thread_id == page_data["thread"], Message.external_id == "root-0"
            )
        )
    result = client.get(page_data["path"] + f"?focus_id={mid}")
    assert result.status_code == 200 and mid in [m["id"] for m in result.json()["items"]]
    assert len(result.json()["root_ids"]) <= 50
    assert client.get(page_data["path"] + "?focus_id=999999").status_code == 404


@pytest.mark.parametrize("bad", ["scheduler", "public_probe", "signature_ok"])
def test_health_outage_once_restore_once_and_restart(client, settings, monkeypatch, bad):
    factory = client.app.state.session_factory
    settings.receive_health_alerts_enabled = True
    settings.notify_line_channel_access_token = SecretStr("fixture-token")
    settings.notify_line_group_id = "C" + "1" * 32
    responses = {"scheduler": True, "public_probe": True}
    monkeypatch.setattr(health, "probe", lambda *a: dict(responses))
    surge = [False]
    monkeypatch.setattr(health, "failure_counts", lambda *a: (12 if surge[0] else 0, surge[0]))
    calls = []
    monkeypatch.setattr(
        health,
        "client",
        lambda: httpx.Client(
            transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200, json={}))
        ),
    )
    now = utc_now()
    health.check(factory, settings, now)
    if bad == "signature_ok":
        surge[0] = True
    else:
        responses[bad] = False
    health.check(factory, settings, now + timedelta(minutes=5))
    health.check(factory, settings, now + timedelta(minutes=10))
    with factory() as s:
        state = health.snapshot(s, settings, now + timedelta(minutes=10))
        assert state["interrupted"] and state["last_ok_at"] == now.isoformat()
    assert len(calls) == 1 and calls[0].url.host == "api.line.me"
    assert "fixture-token" not in calls[0].content.decode()
    responses.update(scheduler=True, public_probe=True)
    surge[0] = False
    health.check(factory, settings, now + timedelta(minutes=15))
    health.check(factory, settings, now + timedelta(minutes=20))
    assert len(calls) == 2
    with factory() as s:
        state = health.snapshot(s, settings, now + timedelta(minutes=20))
        assert not state["interrupted"]
        assert [
            r.transition
            for r in s.scalars(
                select(ReceiveHealthCheck).where(ReceiveHealthCheck.transition.is_not(None))
            )
        ] == ["outage", "recovered"]
        assert len(health.snapshot(s, settings, now + timedelta(hours=25))["history"]) == 0


def test_probe_full_mode_signed_public_and_redirect_rejection(settings, monkeypatch):
    settings.webhook_probe_secret = SecretStr("s" * 32)
    settings.webhook_public_url = "https://example.ngrok.app"
    from types import SimpleNamespace

    from app.services import scheduler

    monkeypatch.setattr(
        scheduler, "scheduler_for", lambda _: SimpleNamespace(healthy=lambda: not missing[0])
    )
    paths = []
    missing = [False]
    redirect = [False]

    def transport(r):
        paths.append(str(r.url))
        if r.url.path == health.PATH:
            material = f"GET\n{health.PATH}\n{r.headers['x-mwb-probe-time']}".encode()
            assert (
                hmac.new(b"s" * 32, material, hashlib.sha256).hexdigest()
                == r.headers["x-mwb-probe-signature"]
            )
            if redirect[0] and r.url.host != "127.0.0.1":
                return httpx.Response(302, headers={"Location": "https://evil.invalid"})
            return httpx.Response(
                200, json={"ok": True, "service": "backend", "purpose": "tunnel-check"}
            )
        return httpx.Response(200, json={})

    monkeypatch.setattr(
        health, "client", lambda: httpx.Client(transport=httpx.MockTransport(transport))
    )
    assert all(health.probe(settings, utc_now()).values())
    missing[0] = True
    assert not health.probe(settings, utc_now())["scheduler"]
    redirect[0] = True
    assert not health.probe(settings, utc_now())["public_probe"]
    assert not any("evil.invalid" in p for p in paths)


def test_fresh_install_without_public_url_is_not_an_outage(client, settings, monkeypatch):
    from types import SimpleNamespace

    from app.services import scheduler

    factory = client.app.state.session_factory
    settings.webhook_public_url = ""
    monkeypatch.setattr(scheduler, "scheduler_for", lambda _: SimpleNamespace(healthy=lambda: True))
    monkeypatch.setattr(health, "client", lambda: pytest.fail("no probe without a public URL"))
    now = utc_now()
    health.check(factory, settings, now)
    with factory() as s:
        state = health.snapshot(s, settings, now)
        assert not state["interrupted"] and state["reasons"] == []
        assert state["public_url_configured"] is False
        assert state["history"][0]["checks"]["public_probe"] is None


@pytest.mark.parametrize(
    ("url", "secret", "reason"),
    [
        ("https://example.com", "s" * 32, "probe_url_invalid"),
        ("https://example.ngrok.app", "", "probe_secret_missing"),
    ],
)
def test_outage_names_its_cause(client, settings, monkeypatch, url, secret, reason):
    from app.services import scheduler

    factory = client.app.state.session_factory
    settings.webhook_public_url = url
    settings.webhook_probe_secret = SecretStr(secret) if secret else None
    monkeypatch.setattr(scheduler, "scheduler_for", lambda _: None)
    monkeypatch.setattr(health, "client", lambda: pytest.fail("no probe without valid config"))
    now = utc_now()
    health.check(factory, settings, now)
    with factory() as s:
        state = health.snapshot(s, settings, now)
        assert state["interrupted"]
        assert state["reasons"] == [health.REASONS["scheduler"], health.REASONS[reason]]


def test_signature_counter_floor_and_relative_spike(client, settings):
    factory = client.app.state.session_factory
    now = utc_now().replace(second=0, microsecond=0)
    with factory() as s:
        for _ in range(9):
            health.signature_failure(s, "line", now - timedelta(minutes=1))
        assert health.failure_counts(s, now) == (9, False)
        health.signature_failure(s, "meta", now - timedelta(minutes=1))
        assert health.failure_counts(s, now) == (10, True)
        for _ in range(120):
            health.signature_failure(s, "line", now - timedelta(minutes=10))
        assert health.failure_counts(s, now) == (10, False)
    assert (
        client.post("/api/ingest/signature-failure", json={"platform": "line"}).status_code == 401
    )
    settings.ingest_api_key = SecretStr("k" * 32)
    assert (
        client.post(
            "/api/ingest/signature-failure",
            headers={"x-api-key": "k" * 32},
            json={"platform": "line"},
        ).status_code
        == 200
    )


def test_target_admin_only_csrf_version_and_default(client, send_data, settings):
    settings.notify_line_group_id = "C" + "2" * 32
    assert (
        client.get("/api/settings/receive-health").json()["recipient"]
        == settings.notify_line_group_id
    )
    value = {"recipient": "U" + "3" * 32, "version": 0}
    assert client.put("/api/settings/receive-health", json=value).status_code == 200
    assert client.put("/api/settings/receive-health", json=value).status_code == 409
    change(send_data, Staff, "staff", role="marketing")
    assert (
        client.put("/api/settings/receive-health", json={**value, "version": 1}).status_code == 403
    )
    assert client.get("/api/receive-health").status_code == 200


def test_parallel_checks_claim_only_one_alert(client, settings, monkeypatch):
    factory = client.app.state.session_factory
    now = utc_now()
    calls = []
    monkeypatch.setattr(health, "probe", lambda *a: {"scheduler": False, "public_probe": False})
    monkeypatch.setattr(health, "push_alert", lambda *a: calls.append(a) or "sent")
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: health.check(factory, settings, now), range(2)))
    assert len(calls) == 1


def test_health_suppression_and_unknown_send_never_retry(client, settings, monkeypatch):
    factory = client.app.state.session_factory
    now = utc_now()
    monkeypatch.setattr(health, "probe", lambda *a: {"scheduler": False, "public_probe": False})
    monkeypatch.setattr(health, "client", lambda: pytest.fail("real alert forbidden"))
    health.check(factory, settings, now)
    with factory() as session:
        assert session.scalar(select(ReceiveHealthCheck)).alert_status == "suppressed"
        assert health.snapshot(session, settings, now)["interrupted"]


def test_process_metadata_preserves_identity_without_cim(monkeypatch):
    import importlib.util
    import os
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "process_info", Path(__file__).parents[2] / "scripts/process_info.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    row = module.process_info(os.getpid())[0]
    assert row["ProcessId"] == os.getpid()
    assert row["ParentProcessId"] > 0 and row["CreationDate"] > 0
    assert "python" in row["CommandLine"].lower() or "pytest" in row["CommandLine"].lower()
    # Exercise enumeration with the real current process, without inspecting every
    # unrelated host process (some Windows processes take seconds to query).
    process = module.psutil.Process(os.getpid())
    monkeypatch.setattr(module.psutil, "process_iter", lambda: iter([process]))
    assert (
        next(r for r in module.process_info() if r["ProcessId"] == os.getpid())["CreationDate"]
        == row["CreationDate"]
    )
