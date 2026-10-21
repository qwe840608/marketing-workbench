"""On-demand reads: independent acceptance expectations, isolated DB and HTTP mocks."""

from datetime import timedelta

import pytest
from alembic import command
from alembic.config import Config
from conftest import call_service, deliver_event
from pydantic import SecretStr
from sqlalchemy import func, select, text
from test_comment_poll import NOW, claim, claim_work, events, finish_work, login, queue
from test_comment_poll import poll_data as poll_data

from app.config import REPO_ROOT
from app.models import Account, AuditLog, CommentPoll, Message, MetaApiCall, Post, Thread
from app.schemas.meta import PollCheckpoint
from app.services import comment_poll, date_ranges
from app.services.gateway_workers import Workers
from app.services.scheduler import Scheduler


def response(rows, after=None):
    body = {"data": rows}
    if after:
        body["paging"] = {"next": "https://untrusted.invalid/", "cursors": {"after": after}}
    return {"statusCode": 200, "body": body, "headers": {}}


@pytest.mark.parametrize("period", ["90", "60", "30", "7", "custom"])
def test_comment_calendar_bounds(period):
    from datetime import UTC, date, datetime

    today = NOW.astimezone(date_ranges.TAIPEI).date()
    start, end = date_ranges.comment_bounds(period, date(2020, 1, 1), date(2020, 1, 2), now=NOW)
    if period == "custom":
        assert start == datetime(2019, 12, 31, 16, tzinfo=UTC)
        assert end == datetime(2020, 1, 2, 16, tzinfo=UTC)
    else:
        assert start.astimezone(date_ranges.TAIPEI).date() == (
            today - timedelta(days=int(period) - 1)
        )
        assert end.astimezone(date_ranges.TAIPEI).date() == today + timedelta(days=1)
        assert (end - start).days == int(period)


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"comment_from": "2020-01-01"},
        {"comment_to": "2020-01-01"},
        {"comment_from": "2020-02-01", "comment_to": "2020-01-01"},
        {"comment_from": "2099-01-01", "comment_to": "2099-01-02"},
        {"comment_from": "2020-02-30", "comment_to": "2020-03-01"},
    ],
)
def test_custom_comment_validation(extra):
    from pydantic import ValidationError

    from app.schemas.ideation import GenerateReport, Reclassify

    for schema in (GenerateReport, Reclassify):
        with pytest.raises(ValidationError):
            schema(
                post_ids=[1],
                start_at=NOW - timedelta(days=700),
                end_at=NOW,
                comment_range="custom",
                **extra,
            )


@pytest.mark.parametrize("platform", ["instagram", "facebook"])
def test_bounded_pages_stop_top_and_replies_and_keep_old_storage(
    client, poll_data, settings, platform
):
    with client.app.state.session_factory.begin() as s:
        s.get(Account, poll_data["accounts"][0]).platform = platform
    # First persist history through an explicit all-history request.
    queue(client, poll_data, period="all")
    runner = worker(
        client, settings, platform, lambda *a, **k: response([row("stored-old", platform, 80)])
    )
    assert runner.comments()["completed"] == 1
    queue(client, poll_data, period="30")
    nested = "comments" if platform == "facebook" else "replies"
    calls = []

    def request(method, url, **kw):
        assert method == "GET"
        cursor = kw["qs"].get("after")
        calls.append(cursor)
        if platform == "facebook":
            assert kw["qs"]["order"] == "reverse_chronological"
        else:
            assert "order" not in kw["qs"]
        if cursor is None:
            return response(
                [
                    row(
                        "root",
                        platform,
                        1,
                        **{nested: response([row("reply", platform, 2)], "reply-page")["body"]},
                    )
                ],
                "top-page",
            )
        if cursor == "reply-page":
            return response([row("old-reply", platform, 50)], "must-not-read-reply")
        assert cursor == "top-page"
        return response(
            [
                row(
                    "old-root",
                    platform,
                    60,
                    **{
                        nested: response(
                            [row("recent-on-old", platform, 3), row("older", platform, 80)],
                            "mixed-reply",
                        )["body"]
                    },
                )
            ],
            "must-not-read-top",
        )

    def with_mixed(method, url, **kw):
        if kw["qs"].get("after") == "mixed-reply":
            calls.append("mixed-reply")
            return response([row("last-old", platform, 100)], "must-not-read-mixed")
        return request(method, url, **kw)

    assert worker(client, settings, platform, with_mixed).comments()["completed"] == 1
    assert calls == [None, "reply-page", "top-page", "mixed-reply"]
    with client.app.state.session_factory() as s:
        assert set(s.scalars(select(Message.external_id))) == {
            "stored-old",
            "root",
            "reply",
            "recent-on-old",
        }
        state = s.scalar(select(CommentPoll).where(CommentPoll.post_id == poll_data["posts"][0]))
        assert state.window_start == date_ranges.date_bounds("30", now=NOW)[0]
        assert state.progress_json["comments_done"] and not state.progress_json["replies"]


def test_omitted_empty_reply_edge_never_adds_requests(client, poll_data, settings):
    queue(client, poll_data)
    calls = []

    def request(method, url, **kw):
        calls.append(url)
        return response([row("no-visible-reply", "instagram")])

    assert worker(client, settings, "instagram", request).comments()["completed"] == 1
    assert len(calls) == 1


def row(identity, platform, days=1, **extra):
    facebook = platform == "facebook"
    return {
        "id": identity,
        "from": {"id": "isolated-audience"},
        "created_time" if facebook else "timestamp": (NOW - timedelta(days=days)).isoformat(),
        "message" if facebook else "text": "[isolated] comment",
        **extra,
    }


def worker(client, settings, platform, request):
    settings.meta_page_id = "111" if platform == "facebook" else ""
    settings.meta_ig_account_id = "111" if platform == "instagram" else ""
    settings.meta_page_access_token = SecretStr("isolated-http-mock")
    return Workers(client.app.state.session_factory, settings, request=request)


@pytest.mark.parametrize("platform", ["instagram", "facebook"])
def test_incremental_existing_pages_replies_and_explicit_full_rescan(
    client, poll_data, settings, platform
):
    with client.app.state.session_factory.begin() as db:
        db.get(Account, poll_data["accounts"][0]).platform = platform
    queue(client, poll_data, period="all")
    nested = "comments" if platform == "facebook" else "replies"
    calls = []

    def request(method, url, **kw):
        calls.append(kw["qs"].get("after"))
        cursor = kw["qs"].get("after")
        if cursor == "top-older":
            return response([row("older-root", platform, 10)])
        if cursor == "reply-older":
            return response([row("older-reply", platform, 10)])
        return response(
            [
                row(
                    "known-root",
                    platform,
                    **{nested: response([row("known-reply", platform)], "reply-older")["body"]},
                )
            ],
            "top-older",
        )

    runner = worker(client, settings, platform, request)
    assert runner.comments()["completed"] == 1
    assert len(calls) == 3  # First read reaches both ends.
    queue(client, poll_data, period="all")
    calls.clear()
    assert runner.comments()["completed"] == 1
    assert calls == [None]
    with client.app.state.session_factory() as db:
        state = db.scalar(select(CommentPoll).where(CommentPoll.post_id == poll_data["posts"][0]))
        assert state.progress_json["new_comments"] == 0
    headers = login(client, poll_data, "marketing")
    path = f"/api/posts/{poll_data['posts'][0]}/comments/sync"
    assert client.post(path + "?period=30&full_rescan=true", headers=headers).status_code == 422
    assert client.post(path + "?period=all&full_rescan=true", headers=headers).status_code == 202
    calls.clear()
    assert runner.comments()["completed"] == 1 and len(calls) == 3
    queue(client, poll_data, period="all")
    calls.clear()

    def with_new_reply(method, url, **kw):
        calls.append(kw["qs"].get("after"))
        if kw["qs"].get("after"):
            return response([row("older-reply", platform, 10)])
        return response(
            [
                row(
                    "known-root",
                    platform,
                    **{nested: response([row("new-reply", platform)], "reply-older")["body"]},
                )
            ],
            "must-not-read-top",
        )

    # The worker transport is injected at construction, not globally patched.
    runner = worker(client, settings, platform, with_new_reply)
    assert runner.comments()["completed"] == 1 and len(calls) == 2
    with client.app.state.session_factory() as db:
        state = db.scalar(select(CommentPoll).where(CommentPoll.post_id == poll_data["posts"][0]))
        assert state.progress_json["new_comments"] == 1


@pytest.mark.parametrize("platform", ["instagram", "facebook"])
@pytest.mark.parametrize("extra_page", [False, True])
def test_expansion_uses_one_call_and_only_overflow_adds_get(
    client, poll_data, settings, platform, extra_page
):
    with client.app.state.session_factory.begin() as session:
        session.get(Account, poll_data["accounts"][0]).platform = platform
        session.get(Post, poll_data["posts"][0]).published_at = NOW - timedelta(days=700)
    queue(client, poll_data)
    calls = []
    nested = "comments" if platform == "facebook" else "replies"
    base_fields = (
        "id,message,created_time,from{id,name},parent{id}"
        if platform == "facebook"
        else "id,text,timestamp,from{id,username}"
    )

    def request(method, url, **kw):
        assert method == "GET"
        assert "access_token" not in kw["qs"]
        calls.append((url.rsplit("/", 2)[-2:], kw["qs"]))
        if len(calls) == 1:
            assert kw["qs"]["limit"] == 50
            assert (
                kw["qs"]["fields"]
                == base_fields
                + ","
                + nested
                + (".filter(stream).order(reverse_chronological)" if platform == "facebook" else "")
                + ".limit(50){"
                + base_fields
                + "}"
            )
            if platform == "facebook":
                assert kw["qs"]["filter"] == "toplevel"
            replies = response([row("r1", platform)], "overflow" if extra_page else None)["body"]
            return response(
                [
                    row("root1", platform, **{nested: replies}),
                    row("root2", platform, **{nested: {"data": []}}),
                ]
            )
        assert url.endswith("/root1/" + nested)
        assert kw["qs"]["after"] == "overflow"
        assert kw["qs"]["fields"] == base_fields
        return response([row("r2", platform)])

    runner = worker(client, settings, platform, request)
    assert runner.comments()["completed"] == 1
    assert len(calls) == 1 + int(extra_page)
    assert runner.comments()["completed"] == 0
    assert len(calls) == 1 + int(extra_page)
    with client.app.state.session_factory() as session:
        assert set(session.scalars(select(Message.external_id))) == (
            {"root1", "root2", "r1", "r2"} if extra_page else {"root1", "root2", "r1"}
        )
        state = session.scalar(
            select(CommentPoll).where(CommentPoll.post_id == poll_data["posts"][0])
        )
        assert state.progress_json["pages"] == 1 + int(extra_page)
        assert state.progress_json["saved_comments"] == 3 + int(extra_page)
        assert not state.manual_requested and state.requested_at is None and state.run_id is None


@pytest.mark.parametrize("platform", ["instagram", "facebook"])
def test_window_keeps_new_reply_to_old_parent_and_reads_all_top_pages(
    client, poll_data, settings, platform
):
    with client.app.state.session_factory.begin() as session:
        session.get(Account, poll_data["accounts"][0]).platform = platform
    queue(client, poll_data)
    nested = "comments" if platform == "facebook" else "replies"
    calls = []

    def request(method, url, **kw):
        calls.append(kw["qs"].get("after"))
        assert "since" not in kw["qs"] and "until" not in kw["qs"]
        if len(calls) == 1:
            return response(
                [
                    row(
                        "old-parent",
                        platform,
                        100,
                        **{
                            nested: {
                                "data": [
                                    row("old-reply", platform, 91),
                                    row("boundary", platform, 90),
                                    row("recent", platform, 1),
                                    row("future", platform, -1),
                                ]
                            }
                        },
                    )
                ],
                "second-top",
            )
        return response(
            [
                row(
                    "older-parent",
                    platform,
                    200,
                    **{
                        nested: {
                            "data": [
                                row("new-on-older", platform, 0.001),
                            ]
                        }
                    },
                )
            ]
        )

    assert worker(client, settings, platform, request).comments()["completed"] == 1
    assert calls == [None, "second-top"]
    with client.app.state.session_factory() as session:
        assert set(session.scalars(select(Message.external_id))) == {
            "old-parent",
            "old-reply",
            "older-parent",
            "boundary",
            "recent",
            "new-on-older",
        }


@pytest.mark.parametrize("role", ["admin", "marketing", "viewer"])
def test_stop_permissions_audit_lease_revocation_and_data_preservation(
    client, poll_data, settings, role
):
    queue(client, poll_data)
    work = claim(client, poll_data)
    from test_comment_poll import poll_event

    event = poll_event(client, poll_data, work)
    event["external_id"] = "poll:isolated-before-stop"
    assert events(client, event, "poll")["created_messages"] == 1
    headers = login(client, poll_data, role)
    stop_path = f"/api/posts/{poll_data['posts'][0]}/comments/stop"
    assert client.post(stop_path).status_code == 403
    assert (
        client.post(
            f"/api/posts/{poll_data['posts'][-1]}/comments/stop", headers=headers
        ).status_code
        == {"admin": 200, "marketing": 404, "viewer": 403}[role]
    )
    response_stop = client.post(stop_path, headers=headers)
    if role == "viewer":
        assert response_stop.status_code == 403
        return
    assert response_stop.json() == {"stopped": True}
    assert claim(client, poll_data) is None
    assert (
        call_service(
            client,
            comment_poll.checkpoint,
            PollCheckpoint,
            {"run_id": work["run_id"], "progress": {}},
        ).status_code
        == 409
    )
    assert (
        deliver_event(client, event, "poll").status_code
        == 409
    )
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 1
        audit = session.scalar(
            select(AuditLog).where(AuditLog.action == "comments.stop").order_by(AuditLog.id.desc())
        )
        assert audit.actor.startswith("staff:") and audit.detail_json == {
            "post_id": poll_data["posts"][0],
            "stopped": True,
        }
    assert (
        client.get(f"/api/posts/{poll_data['posts'][0]}/comments/sync").json()["state"] == "stopped"
    )


def test_stop_during_http_response_does_not_save_or_fetch_next_page(client, poll_data, settings):
    queue(client, poll_data)
    headers = login(client, poll_data, "marketing")
    calls = []

    def request(method, url, **kw):
        calls.append(url)
        assert client.post(
            f"/api/posts/{poll_data['posts'][0]}/comments/stop", headers=headers
        ).json()["stopped"]
        return response([row("stale-after-stop", "instagram", replies={"data": []})], "next")

    worker(client, settings, "instagram", request).comments()
    assert len(calls) == 1
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Message)) == 0
        assert session.scalar(
            select(CommentPoll).where(CommentPoll.post_id == poll_data["posts"][0])
        ).stopped_at


def test_scheduler_requires_manual_job_and_window_survives_budget_resume(
    client, poll_data, settings, monkeypatch
):
    scheduler = Scheduler(client.app.state.session_factory, settings)
    assert not scheduler.claim("comments", NOW)
    queue(client, poll_data)
    assert scheduler.claim("comments", NOW)
    work = claim(client, poll_data)
    finish_work(
        client, {
            "run_id": work["run_id"],
            "success": False,
            "error": "work_budget",
            "progress": {"after": "next-top", "pages": 35, "saved_comments": 120},
        },
    )
    monkeypatch.setattr(comment_poll, "utc_now", lambda: NOW + timedelta(hours=2))
    resumed = claim(client, poll_data)
    assert resumed["window_start"] is None and resumed["window_end"] == NOW.isoformat()
    assert resumed["progress"]["after"] == "next-top" and resumed["progress"]["pages"] == 35


def test_no90_work_budget_resumes_all_history_and_yields_other_post(
    client, poll_data, settings, monkeypatch
):
    factory = client.app.state.session_factory
    settings.meta_api_calls_per_hour = 1000
    queue(client, poll_data)
    old_work = claim(client, poll_data)
    # A legacy cursor cannot certify all-history completion on a new request.
    with factory.begin() as s:
        state = s.scalar(select(CommentPoll).where(CommentPoll.post_id == poll_data["posts"][0]))
        state.window_start = NOW - timedelta(days=90)
        state.progress_json = {"after": "legacy"}
    queue(client, poll_data)
    with factory() as s:
        state = s.scalar(select(CommentPoll).where(CommentPoll.post_id == poll_data["posts"][0]))
        assert state.window_start is None and state.progress_json == {"full_rescan": True}
        assert state.run_id is None
        assert old_work["run_id"] != state.run_id
    requests = []

    def request(method, url, **kw):
        assert method == "GET" and "since" not in kw["qs"]
        requests.append(kw["qs"].get("after"))
        page = int(kw["qs"].get("after", "0"))
        return response(
            [row(f"history-{page}", "instagram", 500)], str(page + 1) if page < 39 else None
        )

    runner = worker(client, settings, "instagram", request)
    assert runner.comments()["completed"] == 0
    assert len(requests) == 35
    with factory() as s:
        state = s.scalar(select(CommentPoll).where(CommentPoll.post_id == poll_data["posts"][0]))
        assert state.progress_json["after"] == "35" and state.manual_requested
    # Another eligible post precedes the resumed job, so it cannot be starved.
    with factory.begin() as s:
        pending = s.scalar(select(CommentPoll).where(CommentPoll.post_id == poll_data["posts"][1]))
        pending.manual_requested, pending.requested_at = True, NOW
        pending.next_poll_at, pending.window_end = NOW - timedelta(seconds=1), NOW
    other = claim_work(
        client, {"platform": "instagram", "account_external_id": "111"}
    )["work"]
    assert other and other["post_id"] == poll_data["posts"][1]
    assert runner.comments()["completed"] == 1
    assert requests == [None, *map(str, range(1, 40))]
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Message)) == 40


def test_no90_api_period_validation_and_old_post_listing(client, poll_data, monkeypatch):
    from unittest.mock import Mock

    from app.services import ideation, ideation_posts

    monkeypatch.setattr(ideation, "utc_now", lambda: NOW)
    monkeypatch.setattr(ideation_posts, "utc_now", lambda: NOW)
    monkeypatch.setattr(ideation, "process", Mock())
    reclassify = Mock()
    monkeypatch.setattr(ideation, "reclassify_all", reclassify)
    pid = poll_data["posts"][0]
    with client.app.state.session_factory.begin() as s:
        s.get(Post, pid).published_at = NOW - timedelta(days=500)
    headers = login(client, poll_data, "admin")
    body = {
        "post_ids": [pid],
        "start_at": (NOW - timedelta(days=600)).isoformat(),
        "end_at": (NOW - timedelta(days=100)).isoformat(),
    }
    query = {"brand_id": poll_data["brand"], "start_at": body["start_at"], "end_at": body["end_at"]}
    listed = client.get("/api/ideation/posts", params=query)
    assert listed.status_code == 200 and [p["id"] for p in listed.json()] == [pid]
    for endpoint, expected in [("reports", 202), ("reclassify", 200)]:
        url = f"/api/ideation/{endpoint}?brand_id={poll_data['brand']}"
        assert client.post(url, json=body, headers=headers).status_code == expected
        response = client.post(
            url, json={**body, "end_at": (NOW + timedelta(seconds=6)).isoformat()}, headers=headers
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "結束時間須晚於開始時間且不得晚於現在"
    reclassify.assert_called_once()
    assert reclassify.call_args.args[-1] == [pid]


@pytest.mark.parametrize("period,expected", [("7", 2), ("30", 3), ("90", 4)])
def test_display_filters_50_groups_and_more_only_read_db(
    client, poll_data, settings, monkeypatch, period, expected
):
    monkeypatch.setattr(date_ranges, "utc_now", lambda: NOW)
    monkeypatch.setattr(Workers, "graph", lambda *a, **kw: pytest.fail("display called Meta"))
    with client.app.state.session_factory.begin() as session:
        thread = Thread(
            brand_id=poll_data["brand"],
            account_id=poll_data["accounts"][0],
            post_id=poll_data["posts"][0],
            kind="comment_thread",
            external_id="display-only",
        )
        session.add(thread)
        session.flush()
        for age in (0, 6, 20, 80, 100):
            for index in range(51):
                session.add(
                    Message(
                        thread_id=thread.id,
                        external_id=f"{age}-{index}",
                        text="[isolated]",
                        sent_at=NOW - timedelta(days=age),
                        direction="in",
                        author_type="fan",
                        comment_parent_known=True,
                    )
                )
    login(client, poll_data, "viewer")
    ids, offset = [], 0
    while offset is not None:
        result = client.get(
            f"/api/posts/{poll_data['posts'][0]}/comment-threads?period={period}&offset={offset}"
        ).json()
        assert len(result["root_ids"]) <= 50
        assert result["root_total"] == 51 * expected
        ids.extend(result["root_ids"])
        offset = result["next_offset"]
    assert len(ids) == len(set(ids)) == 51 * expected
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MetaApiCall)) == 0
        assert session.scalar(select(func.count()).select_from(CommentPoll)) == 0


def test_missing_old_parent_siblings_share_one_group(client, poll_data, monkeypatch):
    monkeypatch.setattr(date_ranges, "utc_now", lambda: NOW)
    with client.app.state.session_factory.begin() as session:
        thread = Thread(
            brand_id=poll_data["brand"],
            account_id=poll_data["accounts"][0],
            post_id=poll_data["posts"][0],
            kind="comment_thread",
            external_id="missing-parent",
        )
        session.add(thread)
        session.flush()
        for i in range(60):
            session.add(
                Message(
                    thread_id=thread.id,
                    external_id=f"reply-{i}",
                    text="[isolated]",
                    sent_at=NOW,
                    direction="in",
                    author_type="fan",
                    comment_parent_known=True,
                    comment_parent_id="old-parent" if i % 2 else "old-nested-reply",
                    comment_root_id="old-parent",
                )
            )
    login(client, poll_data, "viewer")
    result = client.get(f"/api/posts/{poll_data['posts'][0]}/comment-threads?period=30").json()
    assert result["root_total"] == 1 and len(result["root_ids"]) == 1
    assert len(result["items"]) == 60 and result["next_offset"] is None


@pytest.mark.migration
def test_migration_retires_old_jobs_and_preserves_all_records(client, poll_data, monkeypatch):
    config = Config(str(REPO_ROOT / "backend/alembic.ini"))
    with client.app.state.session_factory() as session:
        db_path = session.bind.url.database
    monkeypatch.setenv("DATABASE_PATH", db_path)
    command.downgrade(config, "0024")
    with client.app.state.session_factory.begin() as session:
        session.execute(
            text("""INSERT INTO comment_polls (account_id, post_id, resource, manual_requested,
            next_poll_at, requested_at, run_id, lease_until, progress_json, created_at, updated_at)
            VALUES (:a, :p, 'legacy', 1, :now, :now, '11111111-1111-1111-1111-111111111111',
                :now, '{"replies":[{"id":"old"}]}', :now, :now)"""),
            {"a": poll_data["accounts"][0], "p": poll_data["posts"][0], "now": NOW.isoformat()},
        )
        tables = (
            session.execute(text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"))
            .scalars()
            .all()
        )
        counts = {name: session.scalar(text(f'SELECT count(*) FROM "{name}"')) for name in tables}
        switches = session.execute(text("SELECT id, send_enabled FROM accounts ORDER BY id")).all()
    command.upgrade(config, "0025")
    with client.app.state.session_factory() as session:
        for name, count in counts.items():
            assert session.scalar(text(f'SELECT count(*) FROM "{name}"')) == count
        assert (
            session.execute(text("SELECT id, send_enabled FROM accounts ORDER BY id")).all()
            == switches
        )
        state = session.scalar(select(CommentPoll))
        assert state.stopped_at and not state.manual_requested and state.run_id is None
        assert (
            state.lease_until is None and state.requested_at is None and state.progress_json == {}
        )
        assert session.execute(text("PRAGMA foreign_key_check")).all() == []
    assert claim(client, poll_data) is None
