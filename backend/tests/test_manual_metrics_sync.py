"""貼文數據「立即同步」：排一輪成效同步、60 秒冷卻、執行中不重排、角色限制。"""

from datetime import timedelta

import pytest
from sqlalchemy import select
from test_comment_poll import NOW, login
from test_comment_poll import poll_data as poll_data

from app.models import AuditLog
from app.services import scheduler as service
from app.services.scheduler import Scheduler


@pytest.fixture
def worker(client, settings, monkeypatch):
    clock = {"now": NOW}
    monkeypatch.setattr(service, "utc_now", lambda: clock["now"])
    instance = Scheduler(client.app.state.session_factory, settings)
    monkeypatch.setattr(instance, "healthy", lambda: True)
    monkeypatch.setattr(service, "scheduler_for", lambda value: instance)
    return instance, clock


def sync(client, headers):
    return client.post("/api/scheduler/metrics-sync", headers=headers)


def test_request_queues_metrics_then_cools_down(client, poll_data, worker):
    instance, clock = worker
    headers = login(client, poll_data, "marketing")
    assert client.get("/api/scheduler/metrics-sync").json() == {
        "state": "idle", "finished_at": None, "retry_after": 0,
    }
    response = sync(client, headers)
    assert response.status_code == 202, response.text
    assert response.json() == {
        "state": "pending", "finished_at": None, "retry_after": 60, "queued": True,
    }
    assert instance.wake.is_set()
    # 排程器真的會在下一輪認領這個工作，不必等到整點。
    assert instance.claim("metrics", NOW)
    clock["now"] = NOW + timedelta(seconds=30)
    blocked = sync(client, headers)
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "剛排過同步，請稍候再試"
    assert client.get("/api/scheduler/metrics-sync").json()["retry_after"] == 30
    with client.app.state.session_factory() as session:
        rows = session.scalars(select(AuditLog).where(AuditLog.action == "scheduler.request"))
        assert [row.detail_json for row in rows] == [{"job": "metrics"}]


def test_running_or_pending_job_is_not_queued_again(client, poll_data, worker):
    instance, clock = worker
    headers = login(client, poll_data, "admin")
    instance.request("metrics")
    pending = sync(client, headers)
    assert pending.status_code == 202
    assert pending.json()["state"] == "pending" and pending.json()["queued"] is False
    assert instance.claim("metrics", NOW)
    clock["now"] = NOW + timedelta(seconds=5)
    running = sync(client, headers).json()
    assert running["state"] == "running" and running["queued"] is False
    # 沒排入就不計冷卻，跑完後可以立刻再按。
    assert running["retry_after"] == 0


def test_viewer_disabled_job_and_missing_scheduler(client, poll_data, worker, monkeypatch):
    headers = login(client, poll_data, "viewer")
    assert sync(client, headers).status_code == 403
    assert client.get("/api/scheduler/metrics-sync").status_code == 200
    headers = login(client, poll_data, "admin")
    jobs = client.get("/api/scheduler/jobs").json()["jobs"]
    version = next(job["version"] for job in jobs if job["name"] == "metrics")
    disabled = client.put(
        "/api/scheduler/jobs/metrics", json={"enabled": False, "version": version},
        headers=headers,
    )
    assert disabled.status_code == 200, disabled.text
    assert sync(client, headers).status_code == 409
    monkeypatch.setattr(service, "scheduler_for", lambda value: None)
    assert sync(client, headers).status_code == 503
