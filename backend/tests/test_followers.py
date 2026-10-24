from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, inspect, select, text
from test_comment_poll import login
from test_comment_poll import poll_data as poll_data

from app.config import REPO_ROOT
from app.models import Account, FollowerSnapshot, MetaApiCall, Setting, Staff
from app.schemas.followers import FollowerInput
from app.services import followers, meta_api
from app.services.access import BrandAccess
from app.services.scheduler import Scheduler
from app.services.workers import Workers

NOW = datetime(2026, 10, 5, 2, tzinfo=UTC)  # Monday, Taipei 10:00.


def add(factory, account, values):
    with factory.begin() as session:
        session.add_all(
            [
                FollowerSnapshot(
                    account_id=account,
                    captured_at=datetime.fromisoformat(stamp),
                    followers_count=count,
                )
                for stamp, count in values
            ]
        )


def report(client, data, now=NOW, **selection):
    with client.app.state.session_factory() as session:
        access = BrandAccess(session, session.get(Staff, data["staff"][0]))
        return followers.view(access, "instagram", data["brand"], now=now, **selection)


def test_first_raw_snapshot_baseline_daily_last_negative_and_gaps(client, poll_data):
    add(
        client.app.state.session_factory,
        poll_data["accounts"][0],
        [
            ("2026-10-01T01:00:00Z", 100),
            ("2026-10-01T05:00:00Z", 102),
            ("2026-10-03T01:00:00Z", 97),
        ],
    )
    value = report(client, poll_data)
    assert value["current_count"] == 97
    assert value["month_delta"] == -3
    assert value["week_delta"] is None
    past = report(client, poll_data, year=2026, month=10, week=1)
    assert past["week_delta"] == -3
    assert not past["is_current_week"] and past["is_current_month"]
    assert "period" not in past["accounts"][0]
    assert "recording_since" not in past["accounts"][0]


@pytest.mark.parametrize(
    "now,week_delta,month_delta,week",
    [
        ("2026-09-30T15:59:59Z", 4, 4, 5),
        ("2026-09-30T16:00:00Z", 0, 0, 1),
        ("2026-10-04T15:59:59Z", 2, 2, 1),
        ("2026-10-04T16:00:00Z", 0, -1, 2),
    ],
)
def test_taipei_month_and_monday_midnight(client, poll_data, now, week_delta, month_delta, week):
    add(
        client.app.state.session_factory,
        poll_data["accounts"][0],
        [
            ("2026-09-27T15:59:59Z", 100),
            ("2026-09-28T01:00:00Z", 103),
            ("2026-09-30T15:59:59Z", 104),
            ("2026-09-30T16:00:00Z", 106),
            ("2026-10-04T15:59:59Z", 108),
            ("2026-10-04T16:00:00Z", 105),
        ],
    )
    value = report(client, poll_data, datetime.fromisoformat(now))
    assert value["week_delta"] == week_delta
    assert value["month_delta"] == month_delta
    assert value["week"] == week
    assert value["is_current_week"] and value["is_current_month"]


def test_exact_boundary_and_previous_observation(client, poll_data):
    add(
        client.app.state.session_factory,
        poll_data["accounts"][0],
        [
            ("2026-09-30T10:00:00Z", 100),
            ("2026-10-01T05:00:00Z", 103),
            ("2026-10-04T16:00:00Z", 104),
            ("2026-10-05T01:00:00Z", 106),
        ],
    )
    value = report(client, poll_data)
    assert value["week_delta"] == 2
    assert value["month_delta"] == 6
    assert report(client, poll_data, week=1)["week_delta"] == 3
    old = report(client, poll_data, year=2025, month=1, week=1)
    assert old["week_delta"] is None and old["month_delta"] is None
    assert old["current_count"] == 106
    assert not old["is_current_week"] and not old["is_current_month"]


@pytest.mark.parametrize(
    "year,month,ranges",
    [
        (2026, 10, [(1, 4), (5, 11), (12, 18), (19, 25), (26, 31)]),
        (2026, 12, [(1, 6), (7, 13), (14, 20), (21, 27), (28, 31)]),
        (2027, 1, [(1, 3), (4, 10), (11, 17), (18, 24), (25, 31)]),
        (2026, 2, [(1, 1), (2, 8), (9, 15), (16, 22), (23, 28)]),
        (2024, 2, [(1, 4), (5, 11), (12, 18), (19, 25), (26, 29)]),
        (2026, 3, [(1, 1), (2, 8), (9, 15), (16, 22), (23, 29), (30, 31)]),
        (2026, 6, [(1, 7), (8, 14), (15, 21), (22, 28), (29, 30)]),
    ],
)
def test_month_week_boundaries(year, month, ranges):
    weeks = followers.month_weeks(year, month)
    assert [(w["date_from"].day, w["date_to"].day) for w in weeks] == ranges
    assert [w["week"] for w in weeks] == list(range(1, len(ranges) + 1))


def test_year_options_empty_periods_and_future_snapshots(client, poll_data):
    assert report(client, poll_data)["years"] == [2026]
    add(
        client.app.state.session_factory,
        poll_data["accounts"][0],
        [
            ("2024-12-31T16:00:00Z", 100),
            ("2026-10-01T02:00:00Z", 105),
            ("2026-10-06T02:00:00Z", 999),
        ],
    )
    value = report(client, poll_data)
    assert value["years"] == [2026, 2025]
    assert value["current_count"] == 105
    assert value["week_delta"] is None
    assert value["month_delta"] == 5
    with pytest.raises(Exception, match="週次"):
        report(client, poll_data, month=10, week=6)


def test_generic_platform_record_query_and_account_scope(client, poll_data, monkeypatch):
    factory = client.app.state.session_factory
    monkeypatch.setattr(followers, "utc_now", lambda: NOW)
    with factory.begin() as session:
        account = Account(
            brand_id=poll_data["brand"], platform="youtube", external_id="yt", name="[測試]"
        )
        session.add(account)
        session.flush()
        account_id = account.id
    with factory() as session:
        assert followers.record(
            session,
            FollowerInput(
                platform="youtube", account_external_id="yt", captured_at=NOW, followers_count=41
            ),
        ) == {"inserted": 1}
    login(client, poll_data, "viewer")
    value = client.get(f"/api/posts/followers?platform=youtube&account_id={account_id}").json()
    assert value["connected"] and value["current_count"] == 41
    assert value["week_delta"] == 0
    assert all(a["platform"] == "youtube" for a in value["accounts"])
    assert client.get("/api/posts/followers?platform=facebook").json()["accounts"] == []
    assert not client.get("/api/posts/followers?platform=threads").json()["connected"]
    hidden = client.get(
        f"/api/posts/followers?platform=instagram&account_id={poll_data['accounts'][1]}"
    ).json()
    assert hidden["accounts"] == [] and hidden["current_count"] is None


def test_platform_totals_require_complete_account_data(client, poll_data):
    add(client.app.state.session_factory, poll_data["accounts"][0], [(NOW.isoformat(), 101)])
    with client.app.state.session_factory() as session:
        access = BrandAccess(session, session.get(Staff, poll_data["staff"][0]))
        value = followers.view(access, "instagram", now=NOW)
        assert len(value["accounts"]) == 2
        assert value["current_count"] is None and value["week_delta"] is None
    add(client.app.state.session_factory, poll_data["accounts"][1], [(NOW.isoformat(), 20)])
    with client.app.state.session_factory() as session:
        access = BrandAccess(session, session.get(Staff, poll_data["staff"][0]))
        value = followers.view(access, "instagram", now=NOW)
        assert value["current_count"] == 121 and value["week_delta"] == 0


def test_record_is_idempotent_preserves_zero_and_validates_account(client, poll_data, monkeypatch):
    monkeypatch.setattr(followers, "utc_now", lambda: NOW)
    body = FollowerInput(
        platform="instagram", account_external_id="111", captured_at=NOW, followers_count=0
    )
    factory = client.app.state.session_factory
    for expected in (1, 0):
        with factory() as session:
            assert followers.record(session, body) == {"inserted": expected}
    with factory() as session:
        assert session.scalar(select(FollowerSnapshot)).followers_count == 0
        assert followers.due(session, "instagram", "111", NOW) == {"due": False}
        assert followers.due(session, "instagram", "111", NOW + timedelta(days=1)) == {"due": True}
    with factory() as session, pytest.raises(Exception, match="平台帳號"):
        followers.record(session, body.model_copy(update={"account_external_id": "unknown"}))


@pytest.mark.parametrize("count", [-1, True, "123", 2**53])
def test_invalid_count_rejected(count):
    with pytest.raises(ValidationError):
        FollowerInput(
            platform="facebook", account_external_id="111", captured_at=NOW, followers_count=count
        )


@pytest.mark.parametrize("role", ["admin", "marketing", "viewer"])
def test_api_roles_brand_scope_read_only_and_no_meta(client, poll_data, role, monkeypatch):
    add(client.app.state.session_factory, poll_data["accounts"][0], [(NOW.isoformat(), 101)])
    login(client, poll_data, role)
    monkeypatch.setattr(followers, "utc_now", lambda: NOW)
    graph = Mock(side_effect=AssertionError("query must not call Meta"))
    monkeypatch.setattr(Workers, "graph", graph)
    factory = client.app.state.session_factory
    with factory() as session:
        counts = {
            table: session.scalar(text(f'SELECT count(*) FROM "{table}"'))
            for table in ("follower_snapshots", "meta_api_calls", "audit_log")
        }
    response = client.get("/api/posts/followers?platform=instagram")
    assert response.status_code == 200
    assert len(response.json()["accounts"]) == (2 if role == "admin" else 1)
    value = response.json()["accounts"][0]
    assert value["current"]["followers_count"] == 101
    assert value["week_delta"] == 0
    assert response.json()["year"] == 2026
    assert response.json()["month"] == 10
    assert response.json()["week"] == 2
    for query in (
        "date_from=2026-10-01",
        "date_from=2026-10-05&date_to=2026-10-01",
        "year=0",
        "year=9999",
        "month=13",
        "week=0",
        "week=6",
        "account_id=0",
    ):
        assert client.get("/api/posts/followers?platform=instagram&" + query).status_code == 422
    assert client.get("/api/posts/followers").status_code == 422
    assert client.get("/api/posts/followers?platform=unknown").status_code == 422
    assert (
        client.get("/api/posts/followers?platform=instagram&brand_id=9999").json()["accounts"] == []
    )
    with factory() as session:
        assert counts == {
            table: session.scalar(text(f'SELECT count(*) FROM "{table}"')) for table in counts
        }
    graph.assert_not_called()


def test_api_requires_login(client):
    assert client.get("/api/posts/followers?platform=instagram").status_code == 401


def worker_setup(client, settings, monkeypatch, now=NOW):
    settings.meta_page_id, settings.meta_ig_account_id = "333", "111"
    settings.meta_page_access_token = SecretStr("isolated-test-token")
    monkeypatch.setattr(meta_api, "utc_now", lambda: now)
    monkeypatch.setattr(followers, "utc_now", lambda: now)
    factory = client.app.state.session_factory
    with factory.begin() as session:
        account = session.scalar(select(Account).where(Account.external_id == "111"))
        fb = Account(
            brand_id=account.brand_id, platform="facebook", external_id="333", name="[測試] FB"
        )
        session.add(fb)
    requests = []

    def request(method, url, **kwargs):
        assert method == "GET"
        assert kwargs["qs"] == {"fields": "id,followers_count"}
        requests.append(url)
        return {
            "statusCode": 200,
            "headers": {},
            "body": {
                "id": url.rsplit("/", 1)[1],
                "followers_count": 123,
            },
        }

    return factory, requests, request


def test_worker_daily_get_both_platforms_and_limit(client, poll_data, settings, monkeypatch):
    factory, requests, request = worker_setup(client, settings, monkeypatch)
    worker = Workers(factory, settings, request=request, clock=lambda: NOW.timestamp())
    assert worker.followers() == {"ok": True, "inserted": 2, "errors": []}
    assert len(requests) == 2
    assert worker.followers() == {"ok": True, "inserted": 0, "errors": []}
    assert len(requests) == 2
    with factory() as session:
        calls = list(session.scalars(select(MetaApiCall)))
        assert len(calls) == 2 and all(
            c.source == "metrics" and c.http_status == 200 for c in calls
        )
        assert session.scalar(select(func.count()).select_from(FollowerSnapshot)) == 2
    tomorrow = NOW + timedelta(days=1)
    monkeypatch.setattr(meta_api, "utc_now", lambda: tomorrow)
    monkeypatch.setattr(followers, "utc_now", lambda: tomorrow)
    settings.meta_api_calls_per_hour = 1
    worker.clock = lambda: tomorrow.timestamp()
    outcome = worker.followers()
    assert not outcome["ok"] and outcome["inserted"] == 1
    assert outcome["errors"][-1]["code"] == "meta_rate_limited"
    assert len(requests) == 3


@pytest.mark.parametrize(
    "body",
    [
        {"id": "333"},
        {"id": "333", "followers_count": None},
        {"id": "333", "followers_count": True},
        {"id": "333", "followers_count": -1},
        {"id": "wrong", "followers_count": 5},
    ],
)
def test_unavailable_or_invalid_does_not_record_or_fallback(
    client, poll_data, settings, monkeypatch, body
):
    factory, _, _ = worker_setup(client, settings, monkeypatch)
    settings.meta_ig_account_id = ""
    request = Mock(return_value={"statusCode": 200, "headers": {}, "body": body})
    result = Workers(factory, settings, request=request, clock=lambda: NOW.timestamp()).followers()
    assert not result["ok"] and result["inserted"] == 0
    assert request.call_count == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(FollowerSnapshot)) == 0


def test_rate_header_backoff_blocks_next_account(client, poll_data, settings, monkeypatch):
    factory, _, _ = worker_setup(client, settings, monkeypatch)
    request = Mock(
        return_value={
            "statusCode": 429,
            "headers": {"Retry-After": "7200"},
            "body": {"error": {"code": 4}},
        }
    )
    value = Workers(factory, settings, request=request, clock=lambda: NOW.timestamp()).followers()
    assert not value["ok"] and value["inserted"] == 0 and request.call_count == 1
    with factory() as session:
        assert meta_api.cooldown(session, NOW) == NOW + timedelta(hours=2)


def test_metrics_scheduler_runs_followers_before_posts_and_reports_failure(
    client, poll_data, settings, monkeypatch
):
    scheduler = Scheduler(client.app.state.session_factory, settings)
    assert scheduler.claim("metrics")
    calls = []
    monkeypatch.setattr(
        Workers,
        "followers",
        lambda self: (
            calls.append("followers")
            or {
                "ok": False,
                "inserted": 0,
                "errors": [{"code": "followers_unavailable"}],
            }
        ),
    )
    monkeypatch.setattr(Workers, "metrics", lambda self: calls.append("metrics") or {"ok": True})
    scheduler.execute("metrics")
    assert calls == ["followers", "metrics"]
    with client.app.state.session_factory() as session:
        value = session.scalar(select(Setting).where(Setting.key == "scheduler.job.metrics"))
        assert value.value_json["result"]["ok"] is False
        assert value.value_json["result"]["followers"]["errors"]


def test_start_requests_initial_sync_even_when_next_run_is_future(client, settings, monkeypatch):
    factory = client.app.state.session_factory
    scheduler = Scheduler(factory, settings)
    with factory.begin() as session:
        session.add(
            Setting(key="scheduler.job.metrics", value_json={"next_at": NOW.timestamp() + 3600})
        )
    # Exercise start without starting any thread or an actual service.
    monkeypatch.setattr("threading.Thread.start", lambda self: None)
    scheduler.start()
    assert scheduler.claim("metrics", NOW)
    from app.services import scheduler as module

    module._instances.pop(str(settings.database_path), None)


@pytest.mark.migration
def test_migration_round_trip_preserves_other_data(client, poll_data, settings):
    config = Config(str(REPO_ROOT / "backend/alembic.ini"))
    factory = client.app.state.session_factory
    command.downgrade(config, "0025")
    with factory() as session:
        tables = inspect(session.connection()).get_table_names()
        counts = {
            table: session.scalar(text(f'SELECT count(*) FROM "{table}"'))
            for table in tables
            if table != "alembic_version"
        }
        switches = session.execute(text("SELECT id, send_enabled FROM accounts ORDER BY id")).all()
    for target in ("0026", "0025", "0026"):
        (command.upgrade if target == "0026" else command.downgrade)(config, target)
        with factory() as session:
            names = inspect(session.connection()).get_table_names()
            assert ("follower_snapshots" in names) == (target == "0026")
            assert set(names) == set(tables) | (
                {"follower_snapshots"} if target == "0026" else set()
            )
            assert counts == {
                table: session.scalar(text(f'SELECT count(*) FROM "{table}"')) for table in counts
            }
            assert (
                session.execute(text("SELECT id, send_enabled FROM accounts ORDER BY id")).all()
                == switches
            )
            assert session.execute(text("PRAGMA foreign_key_check")).all() == []
