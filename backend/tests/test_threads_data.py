"""Threads 貼文、成效與回覆：全部使用假 HTTP 回應，不呼叫 Meta 或 Threads。"""

import json
import secrets
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from conftest import login as shared_login
from pydantic import SecretStr
from sqlalchemy import func, select

from app.models import (
    Account,
    Brand,
    CommentPoll,
    Contact,
    FollowerSnapshot,
    InboundJob,
    Message,
    MetaApiCall,
    MetricSnapshot,
    OAuthConnection,
    Post,
    RawEvent,
    Setting,
    Staff,
)
from app.models.base import utc_now
from app.schemas import agent_content
from app.schemas.meta import PollClaim
from app.services import (
    comment_poll,
    followers,
    ideation_posts,
    oauth,
    publish_presence,
)
from app.services import posts as posts_service
from app.services import workers as gateway_workers
from app.services.access import BrandAccess
from app.services.agent_queries import list_posts as mcp_list_posts
from app.services.agent_queries import post_view
from app.services.passwords import hasher
from app.services.workers import Workers
from app.services.workers import metrics as worker_metrics

TOKEN = "isolated-threads-token"
ACCOUNT = "300"
# 固定在過去的整點之後：貼文分級與快照時槽可預期，留言視窗的結束時間（真實現在）一定較晚。
NOW = (utc_now() - timedelta(hours=1)).replace(minute=30, second=0, microsecond=0)
FIELDS = "id,text,permalink,timestamp,media_type"
METRIC_LIST = "views,likes,replies,reposts,quotes,shares"


def stamp(age):
    return (NOW - age).strftime("%Y-%m-%dT%H:%M:%S+0000")


def thread(identity, *, age=timedelta(hours=1), text="[測試] 貼文", media_type="TEXT_POST"):
    row = {
        "id": identity,
        "timestamp": stamp(age),
        "media_type": media_type,
        "permalink": f"https://www.threads.com/@isolated/post/{identity}",
    }
    if text is not None:
        row["text"] = text
    return row


def reply(identity, parent, *, age, text="[測試] 回覆", username="fan_a", own=False):
    row = {
        "id": identity,
        "timestamp": stamp(age),
        "replied_to": {"id": parent},
        "root_post": {"id": "111"},
        "is_reply_owned_by_me": own,
    }
    if text is not None:
        row["text"] = text
    if username is not None:
        row["username"] = username
    return row


def insights(**values):
    return {
        "data": [
            {
                "name": name,
                "period": "lifetime",
                "values": [{"value": value}],
                "title": name,
                "id": f"x/insights/{name}/lifetime",
            }
            for name, value in values.items()
        ]
    }


def total_value(value):
    """使用者層級 followers_count：官方文件的 Total Value 格式（total_value.value）。"""
    row = {"name": "followers_count", "period": "lifetime", "title": "followers", "id": "x"}
    return {"data": [{**row, "total_value": {"value": value}}]}


DEFAULT_INSIGHTS = insights(views=10, likes=3, replies=2, reposts=1, quotes=0, shares=4)


def pages(*entries):
    """依序服務的分頁；整數代表該頁回傳的 HTTP 錯誤狀態，字典代表原樣回應。"""
    result = []
    for index, entry in enumerate(entries):
        if isinstance(entry, (int, dict, tuple)):
            result.append(entry)
            continue
        body = {"data": entry, "paging": {"cursors": {"before": "b", "after": str(index + 1)}}}
        if index + 1 < len(entries):
            body["paging"]["next"] = "https://graph.threads.net/next"
        result.append(body)
    return result


class ThreadsApi:
    """假的 graph.threads.net：記錄每個請求並檢查主機、版本與授權標頭。"""

    def __init__(self):
        self.calls = []
        self.posts = []
        self.insights = {}
        self.replies = {}
        self.endless = False
        self.followers = None

    def __call__(self, method, url, *, headers=None, qs=None, body=None, timeout=15):
        parts = urlsplit(url)
        assert (method, parts.scheme, parts.hostname) == ("GET", "https", "graph.threads.net")
        assert parts.path.startswith("/v1.0/") and not parts.query and body is None
        assert headers == {"Authorization": "Bearer " + TOKEN}
        path, query = parts.path.removeprefix("/v1.0/"), dict(qs or {})
        self.calls.append((path, query))
        identity, _, edge = path.partition("/")
        if edge == "threads":
            assert identity == ACCOUNT
            served = self.serve(self.posts, query.get("after"))
        elif edge == "insights":
            served = self.insights.get(identity, DEFAULT_INSIGHTS)
        elif edge == "conversation":
            served = self.serve(self.replies[identity], query.get("after"))
        elif edge == "threads_insights":
            assert identity == ACCOUNT and query == {"metric": "followers_count"}
            served = self.followers if self.followers is not None else total_value(1234)
        else:
            raise AssertionError(path)
        status, data = served if isinstance(served, tuple) else (200, served)
        return {"statusCode": status, "body": data, "headers": {}}

    def serve(self, listing, after):
        if self.endless:
            number = int(after or 0) + 1
            row = thread(f"e{number}", age=timedelta(days=number))
            body = {"data": [row], "paging": {"next": "x", "cursors": {"after": str(number)}}}
            return 200, body
        entry = listing[int(after or 0)]
        if isinstance(entry, int):
            return entry, {"error": {"code": 1, "message": "private-platform-error"}}
        return entry if isinstance(entry, tuple) else (200, entry)

    def seen(self, edge):
        return [query for path, query in self.calls if path.endswith("/" + edge)]


@pytest.fixture
def env(client, settings, monkeypatch):
    settings.threads_user_id = ACCOUNT
    settings.threads_access_token = SecretStr(TOKEN)
    settings.comments_wake_enabled = False
    settings.ingest_api_key = SecretStr(secrets.token_urlsafe(32))
    clock = {"now": NOW}
    monkeypatch.setattr(posts_service, "utc_now", lambda: clock["now"])
    password = "isolated-" + secrets.token_urlsafe(16)
    factory = client.app.state.session_factory
    with factory.begin() as session:
        brand = Brand(slug="threads-data", name="[測試] Threads")
        session.add(brand)
        session.flush()
        account = Account(
            brand_id=brand.id, platform="threads", external_id=ACCOUNT, name="[測試] Threads"
        )
        admin = Staff(
            username="admin",
            display_name="[測試]",
            role="admin",
            password_hash=hasher.hash(password),
        )
        session.add_all([account, admin])
        session.flush()
        ids = dict(brand=brand.id, account=account.id, admin=admin.id)
    api = ThreadsApi()
    return SimpleNamespace(
        client=client,
        factory=factory,
        settings=settings,
        api=api,
        clock=clock,
        password=password,
        worker=Workers(factory, settings, request=api),
        **ids,
    )


def rows(env, model, *where):
    with env.factory() as session:
        return list(session.scalars(select(model).where(*where)))


def posts_by_id(env):
    return {p.external_id: p for p in rows(env, Post)}


def login(env):
    return shared_login(env.client, "admin", env.password)


def queue(env, post_id, period="all"):
    with env.factory() as session:
        access = BrandAccess(session, session.get(Staff, env.admin))
        return comment_poll.request_sync(
            access, post_id=post_id, settings=env.settings, period=period
        )


def run(env):
    result = env.worker.metrics()
    # 測試環境沒有設定 Meta：結果保留既有的「Meta 設定缺少」旗標，Threads 的成敗看 errors。
    assert result.pop("error") == "meta_configuration_missing" and result.pop("ok") is False
    return {**result, "ok": not result["errors"]}


def block_data_permission(env):
    """既有連結只有發佈權限：數據權限已知缺少。"""
    with env.factory.begin() as session:
        session.add(
            OAuthConnection(
                platform="threads",
                account_name="[測試]",
                granted_scopes=list(oauth.THREADS_PUBLISH_SCOPES),
                credential_digest=oauth.digest_credentials(session, env.settings, "threads"),
                expires_at=utc_now() + timedelta(days=60),
            )
        )


def hours(count):
    return timedelta(hours=count)


def days(count):
    return timedelta(days=count)


def test_listing_pages_write_posts_with_tiers_and_skip_reposts(env, monkeypatch):
    recorded = []
    monkeypatch.setattr(
        publish_presence, "record", lambda *args: recorded.append(args) or {"checked": 0}
    )
    env.api.posts = pages(
        [
            thread("111", age=hours(1), text="第一篇"),
            thread("112", age=days(5), text=None, media_type="IMAGE"),
            thread("113", age=days(6), media_type="REPOST_FACADE"),
        ],
        [thread("114", age=days(40), media_type="VIDEO")],
    )
    result = run(env)
    assert result == {"ok": True, "posts": 3, "snapshots": 3, "errors": []}
    assert env.api.seen("threads") == [
        {"fields": FIELDS, "limit": 100},
        {"fields": FIELDS, "limit": 100, "after": "1"},
    ]
    found = posts_by_id(env)
    assert set(found) == {"111", "112", "114"}
    shown = {k: (p.caption, p.media_type, p.schedule_tier) for k, p in found.items()}
    assert shown == {
        "111": ("第一篇", "TEXT_POST", "hourly"),
        "112": ("", "IMAGE", "daily"),
        "114": ("[測試] 貼文", "VIDEO", "weekly"),
    }
    assert found["111"].permalink == "https://www.threads.com/@isolated/post/111"
    assert abs((found["111"].published_at - (NOW - hours(1))).total_seconds()) < 2
    assert all(p.account_id == env.account for p in found.values())
    # 完整清單（含轉發）交給已刪除偵測重用，不另外多打一次清單。
    assert recorded == [(env.factory, "threads", ACCOUNT, {"111", "112", "113", "114"})]
    assert env.worker.listed == {"threads"}


def test_listing_updates_existing_posts_without_duplicates(env):
    env.api.posts = pages([thread("111", text="舊文案")])
    run(env)
    env.api.posts = pages([thread("111", text="新文案")])
    result = run(env)
    assert result["ok"] and result["posts"] == 1
    assert [p.caption for p in rows(env, Post)] == ["新文案"]


def test_snapshot_maps_threads_metrics(env):
    env.api.posts = pages([thread("111")])
    env.api.insights["111"] = (
        200,
        insights(views=1200, likes=34, replies=5, reposts=2, quotes=1, shares=7),
    )
    assert run(env)["snapshots"] == 1
    assert env.api.seen("insights") == [{"metric": METRIC_LIST}]
    (snapshot,) = rows(env, MetricSnapshot)
    assert (snapshot.views, snapshot.likes, snapshot.comments, snapshot.shares) == (1200, 34, 5, 7)
    assert snapshot.reach is None and snapshot.saves is None and snapshot.avg_watch_time is None
    extra = snapshot.extra_json
    assert (extra["reposts"], extra["quotes"]) == (2, 1)
    assert extra["metric_names"] == {
        "views": "views",
        "likes": "likes",
        "comments": "replies",
        "shares": "shares",
        "reposts": "reposts",
        "quotes": "quotes",
    }
    assert extra["unavailable"] == {
        "reach": "not_available",
        "saves": "not_available",
        "avg_watch_time": "not_available",
        "completion_rate": "not_available",
    }
    assert snapshot.sync_slot == NOW.replace(minute=0)


def test_snapshot_tiers_follow_the_facebook_instagram_schedule(env):
    env.api.posts = pages(
        [thread("111", age=hours(1)), thread("112", age=days(5)), thread("113", age=days(30))]
    )
    assert run(env)["snapshots"] == 3
    # 同一個整點時槽不重複抓。
    assert run(env)["snapshots"] == 0
    env.api.calls.clear()
    env.clock["now"] = NOW + hours(1)
    assert run(env)["snapshots"] == 1
    assert [p for p, _ in env.api.calls if p.endswith("/insights")] == ["111/insights"]
    env.api.calls.clear()
    env.clock["now"] = NOW + hours(24)
    assert run(env)["snapshots"] == 2
    assert sorted(p for p, _ in env.api.calls if p.endswith("/insights")) == [
        "111/insights",
        "112/insights",
    ]
    env.api.calls.clear()
    env.clock["now"] = NOW + hours(24 * 7)
    assert run(env)["snapshots"] == 3


def test_missing_or_unsupported_metrics_are_recorded_not_invented(env):
    env.api.posts = pages([thread("111"), thread("112"), thread("113")])
    env.api.insights["111"] = (200, {"data": []})
    env.api.insights["112"] = (400, {"error": {"code": 100, "message": "private-platform-error"}})
    env.api.insights["113"] = (200, insights(views=0, likes=2, replies=-1, reposts="3"))
    result = run(env)
    assert result["ok"] and result["errors"] == [] and result["snapshots"] == 3
    by_post = {s.post_id: s for s in rows(env, MetricSnapshot)}
    found = posts_by_id(env)
    empty, rejected, partial = (by_post[found[i].id] for i in ("111", "112", "113"))
    assert empty.views is None and empty.extra_json["unavailable"]["views"] == "not_returned"
    assert rejected.likes is None and rejected.extra_json["unavailable"]["likes"] == 100
    # 0 是平台回傳的零；負數或字串不是有效計數，不能存成數字。
    assert (partial.views, partial.likes, partial.comments, partial.shares) == (0, 2, None, None)
    assert partial.extra_json["reposts"] is None and partial.extra_json["quotes"] is None


def test_insight_calls_are_capped_per_run(env, monkeypatch):
    monkeypatch.setattr(worker_metrics, "THREADS_INSIGHT_LIMIT", 2)
    env.api.posts = pages([thread(str(100 + i), age=hours(i + 1)) for i in range(5)])
    assert [run(env)["snapshots"] for _ in range(4)] == [2, 2, 1, 0]
    assert len(env.api.seen("insights")) == 5


def test_known_missing_scopes_skip_insights_and_replies_without_errors(env):
    block_data_permission(env)
    env.api.posts = pages([thread("111")])
    result = run(env)
    assert result == {"ok": True, "posts": 1, "snapshots": 0, "errors": []}
    assert env.api.seen("insights") == [] and rows(env, MetricSnapshot) == []
    queue(env, posts_by_id(env)["111"].id)
    calls = len(env.api.calls)
    outcome = env.worker.comments()
    assert outcome["error"] == "threads_permission_missing" and outcome["ok"] is False
    assert len(env.api.calls) == calls
    (state,) = rows(env, CommentPoll)
    assert state.last_error == "threads_permission_missing" and not state.manual_requested
    login(env)
    status = env.client.get(f"/api/posts/{state.post_id}/comments/sync").json()
    assert status["state"] == "error" and status["last_error"] == "threads_permission_missing"


def test_permission_error_blocks_insights_until_credentials_change(env):
    env.api.posts = pages([thread("111")])
    env.api.insights["111"] = (403, {"error": {"code": 10, "message": "private-platform-error"}})
    result = run(env)
    assert result == {"ok": True, "posts": 1, "snapshots": 0, "errors": []}
    with env.factory() as session:
        assert oauth.threads_data_access(session, env.settings) == "missing"
        assert session.scalar(select(Setting).where(Setting.key == oauth.DATA_BLOCK_KEY))
    # 已標記後不再呼叫成效；貼文清單仍照常同步。
    run(env)
    assert len(env.api.seen("insights")) == 1 and len(env.api.seen("threads")) == 2
    env.settings.threads_access_token = SecretStr("isolated-relinked-token")
    with env.factory() as session:
        assert oauth.threads_data_access(session, env.settings) == "unknown"


def test_rate_limit_and_server_errors_are_reported_as_errors(env):
    env.api.posts = pages([thread("111")])
    for status, body, code in (
        (429, {"error": {"code": 4}}, "meta_rate_limited"),
        (200, {"error": {"code": 190}}, "meta_auth_error"),
        (503, {}, "meta_server_error"),
    ):
        env.api.insights["111"] = (status, body)
        result = run(env)
        assert result["ok"] is False and result["snapshots"] == 0
        assert result["errors"] == [{"platform": "threads", "code": code}]
    assert [p.external_id for p in rows(env, Post)] == ["111"]


@pytest.mark.parametrize(
    ("scenario", "code", "stored"),
    [
        ("http_error", "meta_server_error", {"111", "112"}),
        ("bad_row", "invalid_response", {"111"}),
        ("bad_time", "invalid_response", {"111"}),
        ("bad_data", "posts_unavailable", {"111"}),
        ("repeat_cursor", "invalid_pagination", {"111"}),
    ],
)
def test_incomplete_listing_never_writes_a_bad_page_or_judges_deletion(
    env, monkeypatch, scenario, code, stored
):
    recorded = []
    monkeypatch.setattr(publish_presence, "record", lambda *args: recorded.append(args))
    first = [thread("111")] + ([thread("112")] if scenario == "http_error" else [])
    second = {
        "http_error": 500,
        "bad_row": [thread("112"), {"text": "沒有編號"}],
        "bad_time": [thread("112"), {**thread("113"), "timestamp": "不是時間"}],
        "bad_data": {"data": "oops"},
        "repeat_cursor": {
            "data": [thread("112")],
            "paging": {"next": "x", "cursors": {"after": "1"}},
        },
    }[scenario]
    env.api.posts = pages(first, second)
    result = run(env)
    assert result["ok"] is False and result["errors"] == [{"platform": "threads", "code": code}]
    assert set(posts_by_id(env)) == stored
    assert recorded == [] and rows(env, MetricSnapshot) == []


def test_listing_page_limit_stops_without_judging_deletion(env, monkeypatch):
    recorded = []
    monkeypatch.setattr(publish_presence, "record", lambda *args: recorded.append(args))
    env.api.endless = True
    result = run(env)
    assert result["errors"] == [{"platform": "threads", "code": "discovery_limit"}]
    assert len(env.api.seen("threads")) == gateway_workers.THREADS_PAGE_LIMIT == 50
    assert recorded == [] and len(posts_by_id(env)) == 50


def test_unconfigured_or_unregistered_account_makes_no_calls(env):
    worker = Workers(env.factory, env.settings, request=lambda *a, **k: pytest.fail("no call"))
    env.settings.threads_access_token = None
    assert worker.metrics() == {"ok": False, "error": "meta_configuration_missing"}
    env.settings.threads_access_token = SecretStr(TOKEN)
    with env.factory.begin() as session:
        session.delete(session.get(Account, env.account))
    assert worker.metrics() == {"ok": False, "error": "meta_configuration_missing"}
    assert worker.listed == set()
    with pytest.raises(gateway_workers.WorkerError):
        worker.accounts(True)


def seed_replies(env):
    env.api.posts = pages([thread("111", age=hours(2))])
    run(env)
    post_id = posts_by_id(env)["111"].id
    env.api.replies["111"] = pages(
        [
            reply("r5", "111", age=timedelta(minutes=5), username=None, text="匿名的提問"),
            reply("r4", "111", age=timedelta(minutes=10), username="fan_b", text=None),
            reply("r3", "r2", age=timedelta(minutes=20), text="好的，謝謝"),
        ],
        [
            reply("r2", "r1", age=timedelta(minutes=30), username="isolated_brand", own=True),
            reply("r1", "111", age=timedelta(minutes=40), text="請問價格？"),
        ],
    )
    return post_id


def test_replies_are_saved_like_comments_and_stay_read_only(env):
    post_id = seed_replies(env)
    assert queue(env, post_id) == {"queued": 1}
    assert env.worker.comments() == {"ok": True, "completed": 1, "paused": False}
    assert env.api.seen("conversation") == [
        {"fields": gateway_workers.THREADS_REPLY_FIELDS, "reverse": "true", "limit": 50},
        {
            "fields": gateway_workers.THREADS_REPLY_FIELDS,
            "reverse": "true",
            "limit": 50,
            "after": "1",
        },
    ]
    found = {m.external_id: m for m in rows(env, Message)}
    assert set(found) == {"r1", "r2", "r3", "r4", "r5"}
    assert [(i, found[i].direction, found[i].author_type) for i in ("r1", "r2", "r4")] == [
        ("r1", "in", "fan"),
        ("r2", "out", "brand"),
        ("r4", "in", "fan"),
    ]
    assert (found["r4"].text, found["r5"].text) == ("", "匿名的提問")
    contacts = {c.external_id: c.display_name for c in rows(env, Contact)}
    # 回覆沒有作者編號：自己的回覆歸帳號、他人以使用者名稱、缺名稱的每則獨立。
    assert contacts == {
        "fan_a": "fan_a",
        "fan_b": "fan_b",
        ACCOUNT: "isolated_brand",
        "unknown:r5": "未提供名稱",
    }
    relations = [(found[i].comment_parent_known, found[i].comment_parent_id) for i in ("r1", "r2")]
    relations.append((found["r3"].comment_parent_known, found["r3"].comment_parent_id))
    assert relations == [(True, None), (True, "r1"), (True, "r2")]
    assert {i: found[i].comment_root_id for i in ("r1", "r2", "r3", "r4", "r5")} == {
        "r1": "r1",
        "r2": "r1",
        "r3": "r1",
        "r4": "r4",
        "r5": "r5",
    }
    with env.factory() as session:
        queued = {
            session.get(Message, job.message_id).external_id
            for job in session.scalars(select(InboundJob))
        }
        assert queued == {"r1", "r3", "r4", "r5"}
        events = [e for e in session.scalars(select(RawEvent)) if e.source == "poll"]
        assert events and all(e.processed and e.platform == "threads" for e in events)
        assert {e.account_external_id for e in events} == {ACCOUNT}
        state = session.scalar(select(CommentPoll))
        assert state.last_completed_at and state.progress_json["saved_comments"] == 5
        assert state.progress_json["pages"] == 2 and not state.last_error
    login(env)
    shown = env.client.get(f"/api/posts/{post_id}/comment-threads?period=all").json()
    assert shown["total"] == 5 and len(shown["items"]) == 5 and shown["range_total"] == 5
    names = {i["external_id"]: i["contact_name"] for i in shown["items"]}
    assert names["r2"] == "品牌方（原生平台）" and names["r1"] == "fan_a"
    status = env.client.get(f"/api/posts/{post_id}/comments/sync").json()
    assert status["state"] == "idle" and status["last_completed_at"] and not status["webhook_live"]
    assert status["wait_reason"] is None and status["usage_percent"] is None
    assert env.client.get(f"/api/posts/{post_id}/metrics").status_code == 200


def test_replies_incremental_run_stops_at_known_pages(env):
    post_id = seed_replies(env)
    queue(env, post_id)
    env.worker.comments()
    assert len(env.api.seen("conversation")) == 2
    queue(env, post_id)
    env.worker.comments()
    # 第一頁全是已存回覆就停止，不再往舊頁讀。
    assert len(env.api.seen("conversation")) == 3
    newest = reply("r6", "111", age=timedelta(minutes=1), username="fan_c", text="新的回覆")
    env.api.replies["111"][0]["data"].insert(0, newest)
    queue(env, post_id)
    assert env.worker.comments()["completed"] == 1
    assert len(env.api.seen("conversation")) == 5
    assert {m.external_id for m in rows(env, Message)} == {"r1", "r2", "r3", "r4", "r5", "r6"}
    # 完整重抓才一路讀到底。
    with env.factory() as session:
        access = BrandAccess(session, session.get(Staff, env.admin))
        comment_poll.request_sync(
            access, post_id=post_id, settings=env.settings, period="all", full_rescan=True
        )
    env.worker.comments()
    assert len(env.api.seen("conversation")) == 7


def test_replies_respect_the_comment_window(env):
    env.api.posts = pages([thread("111", age=days(60))])
    run(env)
    post_id = posts_by_id(env)["111"].id
    env.api.replies["111"] = pages(
        [reply("new", "111", age=days(1))],
        [reply("old", "111", age=days(40))],
        [reply("older", "111", age=days(50))],
    )
    queue(env, post_id, period="7")
    assert env.worker.comments()["completed"] == 1
    assert {m.external_id for m in rows(env, Message)} == {"new"}
    # 第二頁已全部早於視窗，不存入也不再讀更舊的第三頁。
    assert len(env.api.seen("conversation")) == 2


def test_reply_errors_become_actionable_or_waiting_states(env):
    post_id = seed_replies(env)
    login(env)
    queue(env, post_id)
    env.api.replies["111"] = pages(403)
    outcome = env.worker.comments()
    assert outcome["error"] == "threads_permission_missing"
    status = env.client.get(f"/api/posts/{post_id}/comments/sync").json()
    assert status["state"] == "error"
    with env.factory() as session:
        assert oauth.threads_data_access(session, env.settings) == "missing"
    # 權限已知缺少時重新抓取不再呼叫平台。
    queue(env, post_id)
    calls = len(env.api.calls)
    assert env.worker.comments()["error"] == "threads_permission_missing"
    assert len(env.api.calls) == calls


def test_reply_rate_limit_waits_without_meta_usage(env):
    post_id = seed_replies(env)
    login(env)
    queue(env, post_id)
    env.api.replies["111"] = [(429, {"error": {"code": 4}})]
    outcome = env.worker.comments()
    assert outcome["error"] == "meta_rate_limited" and outcome["ok"] is True
    status = env.client.get(f"/api/posts/{post_id}/comments/sync").json()
    assert status["state"] == "waiting" and status["wait_reason"] == "threads_usage"
    assert status["usage_percent"] is None and status["calls_per_hour"] is None
    assert status["retry_at"]


def test_threads_replies_ignore_the_meta_call_budget(env):
    post_id = seed_replies(env)
    queue(env, post_id)
    with env.factory.begin() as session:
        blocked = (utc_now() + timedelta(hours=1)).isoformat()
        session.add(
            Setting(
                key="meta.api.budget",
                value_json={"blocked_until": blocked, "reason": "meta_usage"},
            )
        )
    assert env.worker.comments()["completed"] == 1
    assert len(rows(env, Message)) == 5


def test_poll_event_for_threads_never_carries_a_meta_call_record(env):
    post_id = seed_replies(env)
    queue(env, post_id)
    work = env.worker.service(
        comment_poll.claim,
        PollClaim(platform="threads", account_external_id=ACCOUNT),
        env.settings,
    )["work"]
    assert work["platform"] == "threads" and work["post_id"] == post_id
    payload = {"edge": "111/conversation", "data": []}
    body = dict(
        platform="threads",
        account_external_id=ACCOUNT,
        external_id="poll:isolated",
        source="poll",
        signature_ok=False,
        poll_run_id=work["run_id"],
        payload=payload,
        messages=[],
    )
    assert env.worker.save_poll_events(body)["processed"]
    with pytest.raises(gateway_workers.WorkerError):
        env.worker.save_poll_events({**body, "external_id": "poll:call", "poll_call_id": 1})


def test_posts_api_mcp_and_ideation_include_threads(env):
    env.api.posts = pages([thread("111", age=hours(2))])
    env.api.insights["111"] = (
        200,
        insights(views=90, likes=8, replies=3, reposts=2, quotes=1, shares=4),
    )
    run(env)
    post_id = posts_by_id(env)["111"].id
    login(env)
    listed = env.client.get("/api/posts?platform=threads").json()
    assert [p["id"] for p in listed] == [post_id]
    youtube = env.client.get("/api/posts?platform=youtube")
    assert youtube.status_code == 200 and youtube.json() == []
    # TikTok 已串接：貼文清單接受 tiktok，尚未同步時是空清單。
    tiktok = env.client.get("/api/posts?platform=tiktok")
    assert tiktok.status_code == 200 and tiktok.json() == []
    assert env.client.get("/api/posts?platform=line").status_code == 422
    assert env.client.get("/api/posts/platforms").json()["default_platform"] == "threads"
    snapshot = env.client.get(f"/api/posts/{post_id}/metrics").json()[0]
    assert snapshot["views"] == 90 and snapshot["comments"] == 3
    assert (snapshot["extra_json"]["reposts"], snapshot["extra_json"]["quotes"]) == (2, 1)
    with env.factory() as session:
        access = BrandAccess(session, session.get(Staff, env.admin))
        threads = agent_content.Posts(brand_id=env.brand, platform="threads")
        item = mcp_list_posts(access, threads)["items"][0]
        assert item["platform"] == "threads" and item["latest_metrics"]["views"] == 90
        assert (item["latest_metrics"]["reposts"], item["latest_metrics"]["quotes"]) == (2, 1)
        detail = post_view(access, session.get(Post, post_id), detail=True)
        assert detail["snapshots"][0]["likes"] == 8 and detail["snapshots"][0]["reposts"] == 2
        instagram = agent_content.Posts(brand_id=env.brand, platform="instagram")
        assert mcp_list_posts(access, instagram)["items"] == []
        # 主題發想可選用 Threads 貼文：清單、留言預覽（作者遮蔽）與排入讀取都不拒絕。
        picked = ideation_posts.listing(access, env.brand, NOW - days(3), utc_now())
        assert [(p["id"], p["platform"]) for p in picked] == [(post_id, "threads")]
    with env.factory.begin() as session:
        required = ideation_posts.enqueue(
            session,
            env.settings,
            [(session.get(Post, post_id), session.get(Account, env.account))],
            "staff:test",
        )
        assert str(post_id) in required
    mention = "聯絡我 a@example.test"
    env.api.replies["111"] = pages(
        [reply("r1", "111", age=timedelta(minutes=40), username="fan_a", text=mention)]
    )
    assert env.worker.comments()["completed"] == 1
    with env.factory() as session:
        access = BrandAccess(session, session.get(Staff, env.admin))
        preview = ideation_posts.preview_comments(access, env.brand, post_id, "30", None, None, 0)
        (entry,) = preview["items"]
        assert entry["author"] == "f***" and "fan_a" not in json.dumps(entry, default=str)
        assert "a@example.test" not in entry["text"]


def test_due_metrics_service_accepts_threads_account(env):
    # 舊內部路由已移除；worker 直接呼叫此 service 取得 Threads 待抓成效。
    with env.factory() as session:
        assert posts_service.due_metrics(session, "threads", ACCOUNT, 100) == {"posts": []}


def follower_rows(env):
    return rows(env, FollowerSnapshot, FollowerSnapshot.account_id == env.account)


def test_followers_are_saved_for_threads_once_a_day(env):
    result = env.worker.followers()
    assert result == {"ok": True, "inserted": 1, "errors": []}
    assert env.api.calls == [(ACCOUNT + "/threads_insights", {"metric": "followers_count"})]
    (snapshot,) = follower_rows(env)
    assert snapshot.followers_count == 1234
    # 同一天已有快照：到期判斷為否，不再呼叫平台。
    assert env.worker.followers() == {"ok": True, "inserted": 0, "errors": []}
    assert len(env.api.calls) == 1 and len(follower_rows(env)) == 1


def test_followers_view_reports_threads_count_and_weekly_delta(env, monkeypatch):
    now = datetime(2026, 10, 5, 4, tzinfo=UTC)
    monkeypatch.setattr(followers, "utc_now", lambda: now)
    env.worker.clock = lambda: now.timestamp()
    with env.factory.begin() as session:
        for day, count in ((1, 1200), (4, 1237)):
            session.add(FollowerSnapshot(
                account_id=env.account, captured_at=now.replace(day=day), followers_count=count
            ))
    env.worker.followers()
    login(env)
    value = env.client.get("/api/posts/followers?platform=threads").json()
    assert value["connected"] and value["current_count"] == 1234
    assert value["week_delta"] == -3 and value["month_delta"] == 34


def test_followers_accept_values_array_and_zero(env):
    env.api.followers = (
        200,
        {"data": [{"name": "followers_count", "values": [{"value": 0}], "period": "lifetime"}]},
    )
    assert env.worker.followers()["inserted"] == 1
    assert [r.followers_count for r in follower_rows(env)] == [0]


def test_followers_known_missing_scope_makes_no_call_and_no_error(env):
    block_data_permission(env)
    assert env.worker.followers() == {"ok": True, "inserted": 0, "errors": []}
    assert env.api.calls == [] and follower_rows(env) == []


def test_followers_permission_error_marks_data_blocked(env):
    env.api.followers = (403, {"error": {"code": 10, "message": "private-platform-error"}})
    assert env.worker.followers() == {"ok": True, "inserted": 0, "errors": []}
    with env.factory() as session:
        assert oauth.threads_data_access(session, env.settings) == "missing"
        assert session.scalar(select(Setting).where(Setting.key == oauth.DATA_BLOCK_KEY))
    # 已標記後不再呼叫；換權杖（重新連結）才恢復。
    env.worker.followers()
    assert len(env.api.calls) == 1 and follower_rows(env) == []


@pytest.mark.parametrize(
    "body",
    [
        {"data": []},
        {"data": "x"},
        {"data": [None]},
        {"data": [{"name": "followers_count", "values": "x"}]},
        {"data": [{"name": "followers_count", "values": []}]},
        {"data": [{"name": "followers_count", "values": [1]}]},
        {"data": [{"name": "followers_count", "values": [{"value": 1}, {"value": 2}]}]},
        {"data": [{"name": "followers_count", "total_value": {"value": 1}}] * 2},
        {"data": [{"name": "followers_count", "total_value": {"value": 2.0}}]},
        [],
        {"data": [{"name": "views", "total_value": {"value": 5}}]},
        {"data": [{"name": "followers_count"}]},
        {"data": [{"name": "followers_count", "total_value": {"value": None}}]},
        {"data": [{"name": "followers_count", "total_value": {"value": True}}]},
        {"data": [{"name": "followers_count", "total_value": {"value": -1}}]},
        {"data": [{"name": "followers_count", "total_value": {"value": "12"}}]},
        {"data": [{"name": "followers_count", "total_value": {"value": 1.5}}]},
        {"data": [{"name": "followers_count", "total_value": {"value": 2**53}}]},
    ],
)
def test_followers_invalid_format_is_not_saved(env, body, caplog):
    env.api.followers = (200, body)
    result = env.worker.followers()
    assert result == {
        "ok": False,
        "inserted": 0,
        "errors": [{"platform": "threads", "code": "invalid_response"}],
    }
    assert follower_rows(env) == []
    assert "gateway_workers_followers_failed" in caplog.text


@pytest.mark.parametrize(
    "served,code",
    [
        ((429, {"error": {"code": 4}}), "meta_rate_limited"),
        ((500, {}), "meta_server_error"),
        ((401, {"error": {"code": 190}}), "meta_auth_error"),
    ],
)
def test_followers_platform_errors_are_reported_without_saving(env, served, code):
    env.api.followers = served
    result = env.worker.followers()
    assert result["ok"] is False and result["inserted"] == 0
    assert result["errors"] == [{"platform": "threads", "code": code}]
    assert follower_rows(env) == []


def test_followers_unconfigured_or_unregistered_threads_makes_no_call(env):
    worker = Workers(env.factory, env.settings, request=lambda *a, **k: pytest.fail("no call"))
    env.settings.threads_access_token = None
    assert worker.followers() == {
        "ok": False,
        "inserted": 0,
        "errors": [{"code": "meta_configuration_missing"}],
    }
    env.settings.threads_access_token = SecretStr(TOKEN)
    with env.factory.begin() as session:
        session.delete(session.get(Account, env.account))
    assert worker.followers()["errors"] == [{"code": "meta_configuration_missing"}]




def test_followers_becomes_due_at_the_next_taipei_day(env, monkeypatch):
    clock = {"now": datetime(2026, 10, 5, 15, 59, tzinfo=UTC)}
    monkeypatch.setattr(followers, "utc_now", lambda: clock["now"])
    env.worker.clock = lambda: clock["now"].timestamp()
    assert env.worker.followers()["inserted"] == 1
    assert env.worker.followers()["inserted"] == 0
    clock["now"] += timedelta(minutes=1)
    assert env.worker.followers()["inserted"] == 1
    assert len(env.api.calls) == 2 and len(follower_rows(env)) == 2


def test_followers_meta_rate_limit_does_not_skip_threads(env, monkeypatch):
    monkeypatch.setattr(env.worker, "accounts", lambda: [("facebook", "100")])
    original_due = followers.due

    def due(session, platform, account, *args, **kwargs):
        if platform == "facebook":
            return {"due": True}
        return original_due(session, platform, account, *args, **kwargs)

    def graph(*args):
        raise gateway_workers.WorkerError("meta_rate_limited")

    monkeypatch.setattr(followers, "due", due)
    monkeypatch.setattr(env.worker, "graph", graph)
    assert env.worker.followers() == {
        "ok": False, "inserted": 1,
        "errors": [{"platform": "facebook", "code": "meta_rate_limited"}],
    }
    assert [row.followers_count for row in follower_rows(env)] == [1234]


def test_followers_threads_does_not_use_the_meta_call_budget(env):
    env.worker.followers()
    with env.factory() as session:
        assert session.scalar(select(func.count()).select_from(MetaApiCall)) == 0
