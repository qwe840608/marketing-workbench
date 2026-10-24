"""YouTube authorization and reads use fake HTTP only; external sockets are blocked by conftest."""

import json
import secrets
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from conftest import login as shared_login
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select

from app.models import (
    Account,
    AuditLog,
    Brand,
    CommentPoll,
    FollowerSnapshot,
    Message,
    MetricSnapshot,
    OAuthState,
    PlatformCredential,
    Post,
    Setting,
    Staff,
)
from app.models.base import utc_now
from app.schemas import agent_content
from app.services import comment_poll, ideation_posts, oauth, youtube, youtube_oauth
from app.services.access import BrandAccess
from app.services.agent_queries import list_comments, list_posts, post_view
from app.services.passwords import hasher
from app.services.workers import WorkerError, Workers

CHANNEL = "UC_isolated"
VIDEO = "test_video"
ACCESS = "isolated-private-access"
REFRESH = "isolated-private-refresh"


@pytest.fixture
def yt(client, settings, monkeypatch):
    settings.account_encryption_key = SecretStr(Fernet.generate_key().decode())
    settings.youtube_client_id = "isolated.apps.googleusercontent.com"
    settings.youtube_client_secret = SecretStr("isolated-private-secret")
    settings.app_origin = "http://testserver,https://office.example.test"
    settings.comments_wake_enabled = False
    factory = client.app.state.session_factory
    password = secrets.token_urlsafe(32)
    with factory.begin() as session:
        brand = Brand(slug="yt-test", name="[測試] 頻道")
        admin = Staff(
            username="yt-admin",
            display_name="[測試]",
            role="admin",
            password_hash=hasher.hash(password),
        )
        session.add_all([brand, admin])
        session.flush()
        bid, aid = brand.id, admin.id
    client.headers.update(
        shared_login(client, "yt-admin", password) | {"Origin": settings.backoffice_origin}
    )
    calls, options = [], {"invalid": False, "hidden": False, "pages": 2}
    original = httpx.Client

    def handler(request):
        assert request.url.host in {"oauth2.googleapis.com", "www.googleapis.com"}
        calls.append((str(request.url), request.method, request.content))
        if request.url.path == "/token":
            data = parse_qs(request.content.decode())
            assert data["client_id"] == [settings.youtube_client_id]
            assert data["client_secret"] == ["isolated-private-secret"]
            if options["invalid"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            result = dict(
                access_token=ACCESS, expires_in=3600, scope=" ".join(youtube_oauth.SCOPES)
            )
            if data["grant_type"] == ["authorization_code"]:
                result["refresh_token"] = REFRESH
            return httpx.Response(200, json=result)
        if request.url.path == "/revoke":
            if options.get("revoked"):
                return httpx.Response(400, json={"error": "invalid_token"})
            return httpx.Response(200, json={})
        assert request.url.path == "/youtube/v3/channels"
        assert request.headers["authorization"] == "Bearer " + ACCESS
        return httpx.Response(
            200, json={"items": [{"id": CHANNEL, "snippet": {"title": "[測試] YouTube 頻道"}}]}
        )

    monkeypatch.setattr(
        youtube_oauth,
        "httpx",
        SimpleNamespace(
            Client=lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
        ),
    )

    api_calls = []

    def api(method, url, *, headers=None, qs=None, **kwargs):
        assert method == "GET" and headers == {"Authorization": "Bearer " + ACCESS}
        parsed = urlsplit(url)
        assert parsed.hostname in {"www.googleapis.com", "youtubeanalytics.googleapis.com"}
        assert not parsed.query
        edge = parsed.path.rsplit("/", 1)[-1]
        api_calls.append((edge, dict(qs)))
        if edge == "channels":
            data = {
                "items": [
                    dict(
                        id=CHANNEL,
                        contentDetails={"relatedPlaylists": {"uploads": "UU_test"}},
                        statistics={
                            "subscriberCount": "1234",
                            "hiddenSubscriberCount": options["hidden"],
                        },
                    )
                ]
            }
        elif edge == "playlistItems":
            page = int(qs.get("pageToken", "0"))
            data = {"items": [{"contentDetails": {"videoId": VIDEO + str(page)}}]}
            if page + 1 < options["pages"]:
                data["nextPageToken"] = str(page + 1)
        elif edge == "videos":
            data = {
                "items": [
                    dict(
                        id=identity,
                        snippet={
                            "channelId": CHANNEL,
                            "title": "[測試] 影片 " + identity,
                            "publishedAt": (utc_now() - timedelta(days=4)).isoformat(),
                        },
                        contentDetails={"duration": "PT3M" if identity.endswith("0") else "PT4M"},
                        status={
                            "privacyStatus": "unlisted" if identity.endswith("0") else "public"
                        },
                        statistics={"viewCount": "100", "likeCount": "5", "commentCount": "3"},
                    )
                    for identity in qs["id"].split(",")
                ]
            }
        elif edge == "reports":
            assert qs["filters"].startswith("video==")
            assert qs["ids"] == "channel==" + CHANNEL
            data = {
                "columnHeaders": [{"name": name} for name in youtube.ANALYTICS_METRICS],
                "rows": [[30, 120, 4, 2, 62.5]],
            }
        elif edge == "commentThreads":
            page = int(qs.get("pageToken", "0"))
            data = {
                "items": [
                    {
                        "snippet": {
                            "topLevelComment": comment("top" + str(page)),
                            "totalReplyCount": 2 if page == 0 else 0,
                        },
                        "replies": {"comments": [comment("reply0", "top0")]} if page == 0 else {},
                    }
                ]
            }
            if page == 0:
                data["nextPageToken"] = "1"
        elif edge == "comments":
            page = int(qs.get("pageToken", "0"))
            data = {"items": [comment("reply" + str(page), "top0")]}
            if page == 0:
                data["nextPageToken"] = "1"
        else:
            raise AssertionError(edge)
        return dict(statusCode=200, body=data, headers={})

    def comment(identity, parent=None):
        return {
            "id": identity,
            "snippet": {
                "publishedAt": (utc_now() - timedelta(hours=2)).isoformat(),
                "textOriginal": "[測試] 問題 0912345678 isolated@example.test",
                "authorDisplayName": "[測試] 原始作者",
                "authorChannelId": {"value": "UC_fan"},
                **({"parentId": parent} if parent else {}),
            },
        }

    return SimpleNamespace(
        client=client,
        settings=settings,
        factory=factory,
        brand=bid,
        admin=aid,
        calls=calls,
        api_calls=api_calls,
        options=options,
        worker=Workers(factory, settings, request=api),
    )


def begin(yt):
    response = yt.client.post("/api/oauth/youtube/start", json={})
    assert response.status_code == 200, response.text
    args = parse_qs(urlsplit(response.json()["url"]).query)
    assert args["access_type"] == ["offline"] and args["prompt"] == ["consent"]
    scopes = args["scope"][0].split()
    assert set(scopes) == set(youtube_oauth.SCOPES)
    # 發佈只新增 youtube.upload；不要求權限更廣的 youtube 或 force-ssl。
    assert "https://www.googleapis.com/auth/youtube.upload" in scopes
    broader = {
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/youtube.force-ssl",
    }
    assert not broader & set(scopes)
    return args["state"][0]


def receive(yt, state):
    cookies = dict(yt.client.cookies)
    yt.client.cookies.clear()
    try:
        response = yt.client.get(
            "/api/oauth/youtube/callback",
            params={"state": state, "code": "isolated-private-code"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        return response
    finally:
        yt.client.cookies.update(cookies)


def link(yt):
    response = receive(yt, begin(yt))
    assert "oauth_pending=youtube" in response.headers["location"]
    done = yt.client.post("/api/oauth/youtube/complete", json={})
    assert done.status_code == 200 and done.json()["result"] == "linked", done.text


def rows(yt, model):
    with yt.factory() as session:
        return list(session.scalars(select(model)))


def test_oauth_encryption_refresh_invalid_grant_disconnect(yt):
    link(yt)
    status = yt.client.get("/api/oauth/status").json()["platforms"]["youtube"]
    assert status["state"] == "ready" and status["name"] == "[測試] YouTube 頻道"
    assert status["configured"]
    assert youtube_oauth.access_token(yt.factory, yt.settings) == ACCESS
    assert len(yt.calls) == 2
    with yt.factory.begin() as session:
        oauth.connection(session, "youtube").expires_at = utc_now() - timedelta(seconds=1)
    assert youtube_oauth.access_token(yt.factory, yt.settings) == ACCESS
    assert parse_qs(yt.calls[-1][2].decode())["refresh_token"] == [REFRESH]
    with yt.factory.begin() as session:
        oauth.connection(session, "youtube").expires_at = utc_now() - timedelta(seconds=1)
    yt.options["invalid"] = True
    with pytest.raises(oauth.ProviderFailure):
        youtube_oauth.access_token(yt.factory, yt.settings)
    status = yt.client.get("/api/oauth/status").json()["platforms"]["youtube"]
    assert status["state"] == "failed"
    count = len(yt.calls)
    with pytest.raises(oauth.ProviderFailure):
        youtube_oauth.access_token(yt.factory, yt.settings)
    assert len(yt.calls) == count
    yt.options["invalid"] = False
    link(yt)
    assert yt.client.get("/api/oauth/status?force=true").json()["platforms"]["youtube"]["verified"]
    secrets_to_hide = [ACCESS, REFRESH, "isolated-private-secret", "isolated-private-code"]
    serial = json.dumps([a.detail_json for a in rows(yt, AuditLog)])
    serial += yt.client.get("/api/credentials").text
    for value in secrets_to_hide:
        assert value not in serial
        assert value.encode() not in yt.settings.database_path.read_bytes()
    assert all(r.encrypted_key != REFRESH for r in rows(yt, PlatformCredential))
    yt.options["revoked"] = True
    with yt.factory.begin() as session:
        channel = session.scalar(select(Account).where(Account.platform == "youtube"))
        session.add(Post(account_id=channel.id, external_id="disconnect-video", caption="說明",
                         media_type="VIDEO", published_at=utc_now()))
    response = yt.client.post("/api/oauth/youtube/disconnect", json={})
    assert response.status_code == 200
    # 撤銷授權後同步取得的資料立即刪除（YouTube 政策要求 7 天內），帳號名稱也換掉。
    assert response.json()["removed"]["posts"] >= 1
    assert yt.calls[-1][0] == "https://oauth2.googleapis.com/revoke"
    assert not yt.client.get("/api/oauth/status").json()["platforms"]["youtube"]["linked"]
    assert rows(yt, Account)[0].status == "disconnected"
    with yt.factory() as session:
        youtube = select(Account.id).where(Account.platform == "youtube")
        assert not session.scalars(select(Post).where(Post.account_id.in_(youtube))).all()
        assert {a.name for a in session.scalars(select(Account).where(
            Account.platform == "youtube"))} == {"YouTube"}


@pytest.mark.parametrize("case", ["wrong", "expired", "replay", "session", "staff", "platform"])
def test_oauth_state(yt, case):
    state = begin(yt)
    if case == "replay":
        receive(yt, state)
        assert yt.client.post("/api/oauth/youtube/complete", json={}).json()["result"] == "linked"
    with yt.factory.begin() as session:
        row = session.scalar(select(OAuthState).order_by(OAuthState.id.desc()))
        if case == "expired":
            row.expires_at = utc_now() - timedelta(seconds=1)
        elif case == "session":
            row.session_hash = "different"
        elif case == "staff":
            row.staff_id += 1
        elif case == "platform":
            row.platform = "meta"
    count = len(yt.calls)
    response = receive(yt, "wrong" if case == "wrong" else state)
    if "oauth_pending" in response.headers["location"]:
        assert yt.client.post("/api/oauth/youtube/complete", json={}).status_code == 400
    else:
        assert "oauth_result=failed" in response.headers["location"]
    assert len(yt.calls) == count


def test_oauth_permission_csrf_public_boundary(yt):
    assert (
        yt.client.post(
            "/api/oauth/youtube/start", json={}, headers={"X-CSRF-Token": "bad"}
        ).status_code
        == 403
    )
    assert (
        yt.client.post(
            "/api/oauth/youtube/disconnect", json={}, headers={"X-CSRF-Token": "bad"}
        ).status_code
        == 403
    )
    with yt.factory.begin() as session:
        session.get(Staff, yt.admin).role = "viewer"
    assert yt.client.post("/api/oauth/youtube/start", json={}).status_code == 403
    assert yt.client.post("/api/oauth/youtube/complete", json={}).status_code == 403
    # 教學改由前端彈出視窗呈現，後端不再提供文字端點。
    assert yt.client.get("/api/oauth/youtube/guide").status_code == 404
    assert (
        yt.client.get("/api/oauth/youtube/callback", headers={"X-MWB-Public": "1"}).status_code
        == 404
    )
    assert not yt.calls


def test_metrics_followers_comments_mcp(yt):
    link(yt)
    result = yt.worker.metrics()
    assert result["ok"] and result["posts"] == result["snapshots"] == 2
    stored = rows(yt, Post)
    assert [p.media_type for p in stored] == ["SHORTS", "VIDEO"]
    assert [p.visibility for p in stored] == ["unlisted", "public"]
    assert all(p.schedule_tier == "daily" for p in stored)
    snapshots = rows(yt, MetricSnapshot)
    assert all(
        (m.views, m.likes, m.comments, m.shares, float(m.avg_watch_time)) == (100, 5, 3, 4, 30)
        for m in snapshots
    )
    assert all(
        m.extra_json["watch_hours"] == 2
        and m.extra_json["subscribers_gained"] == 2
        and m.extra_json["avg_view_percentage"] == 62.5
        for m in snapshots
    )
    assert yt.worker.followers()["inserted"] == 1
    assert yt.worker.followers()["inserted"] == 0
    assert rows(yt, FollowerSnapshot)[0].followers_count == 1234
    post = stored[0]
    with yt.factory() as session:
        access = BrandAccess(session, session.get(Staff, yt.admin))
        comment_poll.request_sync(access, post_id=post.id, settings=yt.settings, period="all")
    result = yt.worker.comments(requested_only=True, post_id=post.id)
    assert result["completed"] == 1, result
    assert len(rows(yt, Message)) == 4
    assert rows(yt, CommentPoll)[0].manual_requested is False
    assert [qs.get("pageToken") for edge, qs in yt.api_calls if edge == "comments"] == [None, "1"]
    with yt.factory() as session:
        access = BrandAccess(session, session.get(Staff, yt.admin))
        projected = post_view(access, session.get(Post, post.id), detail=True)
        assert projected["latest_metrics"]["watch_hours"] == 2
        assert projected["latest_metrics"]["subscribers_gained"] == 2
        response = list_posts(access, agent_content.Posts(brand_id=yt.brand, platform="youtube"))
        assert response["items"] and all(p["platform"] == "youtube" for p in response["items"])
        evidence = list_comments(access, agent_content.Comments(brand_id=yt.brand, post_id=post.id))
        text = json.dumps(evidence, default=str)
        assert "0912345678" not in text and "isolated@example.test" not in text
        assert "[測試] 原始作者" not in text
        assert ideation_posts.listing_for_window(
            access, yt.brand, utc_now() - timedelta(days=10), utc_now(), "all", None, None
        )  # shared source picker
    content = yt.client.get(f"/api/posts/{post.id}/comment-threads?period=all").json()
    assert len(content["items"]) == 4
    text = json.dumps(content)
    assert "0912345678" not in text and "isolated@example.test" not in text
    assert "[測試] 原始作者" not in text
    assert yt.client.get("/api/posts?platform=youtube").status_code == 200


@pytest.mark.parametrize(
    "iso,expected", [("PT0S", True), ("PT3M", True), ("PT180.1S", False), ("PT1H2M3S", False)]
)
def test_shorts(iso, expected):
    assert youtube.short({"contentDetails": {"duration": iso}}) is expected


def test_hidden_quota_and_cursor_limits(yt, monkeypatch):
    link(yt)
    yt.options["hidden"] = True
    assert yt.worker.followers()["inserted"] == 0
    assert not rows(yt, FollowerSnapshot)
    count = len(yt.api_calls)
    assert yt.worker.followers()["inserted"] == 0 and len(yt.api_calls) == count
    assert yt.client.get("/api/posts/followers?platform=youtube").json()["subscriber_hidden"]
    yt.options["pages"] = 4
    monkeypatch.setattr(youtube, "PAGE_LIMIT", 1)
    yt.worker.metrics()
    yt.worker.metrics()
    assert [qs.get("pageToken") for edge, qs in yt.api_calls if edge == "playlistItems"] == [
        None,
        "1",
    ]
    reader = youtube.Sync(yt.worker)
    monkeypatch.setattr(youtube, "ROUND_LIMIT", 0)
    count = len(yt.api_calls)
    with pytest.raises(WorkerError, match="work_budget"):
        reader.get("channels", {})
    assert len(yt.api_calls) == count
    monkeypatch.setattr(youtube, "ROUND_LIMIT", 420)
    with yt.factory.begin() as session:
        row = session.scalar(select(Setting).where(Setting.key == "youtube.quota"))
        row.value_json = {**row.value_json, "used": youtube.DAILY_LIMIT}
    with pytest.raises(WorkerError, match="meta_rate_limited"):
        reader.get("channels", {})
    assert len(yt.api_calls) == count


def test_rejects_missing_refresh_scope_channel_or_brand(yt, monkeypatch):
    original = youtube_oauth.request
    for broken in ("refresh", "scope", "channel"):

        def invalid(url, broken=broken, **kwargs):
            result = original(url, **kwargs)
            if url == youtube_oauth.TOKEN_URL:
                result = {**result}
                if broken == "refresh":
                    result.pop("refresh_token", None)
                if broken == "scope":
                    result["scope"] = youtube_oauth.SCOPES[0]
            elif url == youtube_oauth.CHANNEL_URL:
                result = {"items": [] if broken == "channel" else result["items"]}
            return result

        monkeypatch.setattr(youtube_oauth, "request", invalid)
        receive(yt, begin(yt))
        assert yt.client.post("/api/oauth/youtube/complete", json={}).json()["result"] == "failed"
        assert not rows(yt, Account)
        assert not rows(yt, PlatformCredential)
        monkeypatch.setattr(youtube_oauth, "request", original)
    with yt.factory.begin() as session:
        session.add(Brand(slug="other-brand", name="[測試] 另一品牌"))
    receive(yt, begin(yt))
    assert yt.client.post("/api/oauth/youtube/complete", json={}).json()["result"] == "failed"
    assert not rows(yt, Account) and not rows(yt, PlatformCredential)


def test_link_without_upload_scope_keeps_reads_and_reports_missing_upload(yt, monkeypatch):
    upload = youtube_oauth.UPLOAD_SCOPES[0]
    original = youtube_oauth.request

    def read_only(url, **kwargs):
        result = original(url, **kwargs)
        if url == youtube_oauth.TOKEN_URL:
            # Google 允許使用者在授權畫面取消勾選個別權限。
            result = {**result, "scope": " ".join(youtube_oauth.READ_SCOPES)}
        return result

    monkeypatch.setattr(youtube_oauth, "request", read_only)
    link(yt)
    status = yt.client.get("/api/oauth/status").json()["platforms"]["youtube"]
    assert status["state"] == "ready" and status["missing"] == []
    assert status["data_missing"] == [upload]
    assert set(status["granted"]) == set(youtube_oauth.READ_SCOPES)
    # 讀取功能照常；只是發佈需要重新連結取得上傳權限。
    assert yt.worker.metrics()["ok"]
    monkeypatch.setattr(youtube_oauth, "request", original)
    link(yt)
    status = yt.client.get("/api/oauth/status").json()["platforms"]["youtube"]
    assert status["data_missing"] == [] and set(status["granted"]) == set(youtube_oauth.SCOPES)


def test_recent_reply_on_old_parent_and_full_rescan_are_idempotent(yt):
    link(yt)
    yt.worker.metrics()
    post = rows(yt, Post)[0]
    original = yt.worker.request

    def old_parent(method, url, **kwargs):
        response = original(method, url, **kwargs)
        if url.endswith("/commentThreads"):
            for item in response["body"]["items"]:
                snippet = item["snippet"]["topLevelComment"]["snippet"]
                snippet["publishedAt"] = (utc_now() - timedelta(days=200)).isoformat()
        return response

    yt.worker.request = old_parent
    with yt.factory() as session:
        access = BrandAccess(session, session.get(Staff, yt.admin))
        comment_poll.request_sync(access, post_id=post.id, settings=yt.settings, period="7")
    assert yt.worker.comments(requested_only=True, post_id=post.id)["completed"] == 1
    assert {m.external_id for m in rows(yt, Message)} == {"reply0", "reply1"}
    for full in (True, True):
        with yt.factory() as session:
            access = BrandAccess(session, session.get(Staff, yt.admin))
            comment_poll.request_sync(
                access, post_id=post.id, settings=yt.settings, period="all", full_rescan=full
            )
        assert yt.worker.comments(requested_only=True, post_id=post.id)["completed"] == 1
    assert {m.external_id for m in rows(yt, Message)} == {"top0", "top1", "reply0", "reply1"}
    assert len(rows(yt, Message)) == 4
    with yt.factory() as session:
        access = BrandAccess(session, session.get(Staff, yt.admin))
        comment_poll.request_sync(access, post_id=post.id, settings=yt.settings, period="7")
        comment_poll.stop(access, post.id)
    count = len(yt.api_calls)
    assert yt.worker.comments(requested_only=True, post_id=post.id)["completed"] == 0
    assert len(yt.api_calls) == count


def test_invalid_page_and_analytics_failure_preserve_realtime(yt):
    link(yt)
    original = yt.worker.request

    def broken(method, url, **kwargs):
        response = original(method, url, **kwargs)
        if url.endswith("/playlistItems"):
            response["body"]["nextPageToken"] = kwargs["qs"].get("pageToken", "")
        return response

    yt.worker.request = broken
    result = yt.worker.metrics()
    assert not result["ok"] and result["errors"][0]["code"] == "invalid_pagination"
    assert not rows(yt, Post)

    def denied_report(method, url, **kwargs):
        if url == youtube.ANALYTICS:
            return {"statusCode": 403, "body": {"error": {"errors": []}}}
        return original(method, url, **kwargs)

    yt.worker.request = denied_report
    assert yt.worker.metrics()["snapshots"] == 2
    assert all(
        m.views == 100
        and m.shares is None
        and m.avg_watch_time is None
        and m.extra_json["watch_hours"] is None
        and m.extra_json["analytics_error"] == "youtube_permission_missing"
        for m in rows(yt, MetricSnapshot)
    )


@pytest.mark.parametrize(
    "status,expected",
    [({"privacyStatus": "private"}, "private"), ({"privacyStatus": "x"}, None), ({}, None)],
)
def test_visibility(status, expected):
    assert youtube.visibility({"status": status}) == expected


def test_posts_missing_from_complete_listing_are_hidden_and_restored(yt):
    # 完整清單裡沒有的貼文（在平台上刪除）不在貼文數據顯示；重新出現時恢復。
    from app.services import publish_presence

    link(yt)
    assert yt.worker.metrics()["ok"]
    stored = {p.external_id for p in rows(yt, Post)}
    assert len(stored) == 2
    kept, gone = sorted(stored)

    def shown():
        return {p["external_id"] for p in yt.client.get("/api/posts?platform=youtube").json()}

    assert shown() == stored
    publish_presence.record(yt.factory, "youtube", CHANNEL, {kept})
    assert shown() == {kept}
    assert [p.external_id for p in rows(yt, Post) if p.deleted_at] == [gone]
    # 空清單不判定，避免權限或帳號異常時把全部貼文隱藏。
    publish_presence.record(yt.factory, "youtube", CHANNEL, set())
    assert shown() == {kept}
    publish_presence.record(yt.factory, "youtube", CHANNEL, stored)
    assert shown() == stored


def test_unexpected_youtube_error_is_recorded_without_failing_the_job(yt, monkeypatch):
    # 資料庫忙碌等非預期錯誤只記在 YouTube，不讓每小時的整批工作中斷。
    def broken(self, result):
        raise RuntimeError("isolated-unexpected")

    link(yt)
    monkeypatch.setattr(youtube.Sync, "snapshots", broken)
    monkeypatch.setattr(youtube.Sync, "followers", broken)
    assert {"platform": "youtube", "code": "sync_failed"} in yt.worker.metrics()["errors"]
    assert {"platform": "youtube", "code": "sync_failed"} in yt.worker.followers()["errors"]
