"""TikTok 數據同步：全部以假 HTTP 驗證，不連 TikTok。

公開影片與成效同一次清單取得、分頁走完才判定消失（已刪除或改為私人）、清單不完整或為空不判定、
粉絲數每日一次、授權失效時不呼叫 TikTok。
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import select
from test_tiktok_oauth import link
from test_tiktok_oauth import tt as tt

from app.models import FollowerSnapshot, MetricSnapshot, Post
from app.models.base import utc_now
from app.services import oauth, tiktok
from app.services.gateway_workers import Workers

ACCESS = "isolated-tiktok-access"


def video(identity, views=100):
    return dict(
        id=identity,
        title="[測試] 影片 " + identity,
        create_time=1760000000,
        share_url="https://www.tiktok.com/@isolated/video/" + identity,
        duration=30,
        view_count=views,
        like_count=5,
        comment_count=2,
        share_count=1,
    )


@pytest.fixture
def sync(tt):
    assert link(tt).json()["result"] == "linked"
    state = {
        "pages": [[video("v1"), video("v2")], [video("v3")]],
        "followers": 321,
        "fail_page": None,
        "status": 200,
    }
    calls = []

    def api(method, url, *, headers=None, qs=None, body=None, **kwargs):
        assert headers == {"Authorization": "Bearer " + ACCESS}
        calls.append((method, url, dict(qs or {}), body))
        if state["status"] != 200:
            return dict(
                statusCode=state["status"], body={"error": {"code": "access_token_invalid"}}
            )
        if url == tiktok.VIDEO_URL:
            assert method == "POST" and "view_count" in qs["fields"]
            page = (body or {}).get("cursor", 0)
            if page == state["fail_page"]:
                return dict(statusCode=500, body={})
            rows = state["pages"][page] if page < len(state["pages"]) else []
            more = page + 1 < len(state["pages"])
            data = {"videos": rows, "cursor": page + 1, "has_more": more}
            return dict(statusCode=200, body={"data": data, "error": {"code": "ok"}})
        assert url == tiktok.USER_URL and qs["fields"] == "open_id,follower_count"
        user = {"open_id": "isolated-open-id", "follower_count": state["followers"]}
        return dict(statusCode=200, body={"data": {"user": user}, "error": {"code": "ok"}})

    return SimpleNamespace(
        tt=tt, state=state, calls=calls, worker=Workers(tt.factory, tt.settings, request=api)
    )


def posts(sync):
    with sync.tt.factory() as session:
        return {p.external_id: p for p in session.scalars(select(Post))}


def test_listing_writes_public_videos_and_snapshots_from_the_same_call(sync):
    result = sync.worker.metrics()
    assert result["posts"] == 3 and result["snapshots"] == 3, result
    rows = posts(sync)
    assert set(rows) == {"v1", "v2", "v3"}
    assert rows["v1"].visibility == "public" and rows["v1"].permalink.startswith("https://")
    with sync.tt.factory() as session:
        snap = session.scalar(select(MetricSnapshot).join(Post).where(Post.external_id == "v1"))
        assert (snap.views, snap.likes, snap.comments, snap.shares) == (100, 5, 2, 1)
    # 成效直接取自清單：只打清單 API，沒有逐支查詢。
    assert {url for _, url, *_ in sync.calls} == {tiktok.VIDEO_URL}
    assert [b.get("cursor") for *_, b in sync.calls] == [None, 1]


def test_complete_listing_hides_vanished_videos_and_restores_them(sync):
    sync.worker.metrics()
    sync.state["pages"] = [[video("v1")], [video("v3")]]
    sync.worker.metrics()
    rows = posts(sync)
    assert rows["v2"].deleted_at is not None
    assert rows["v1"].deleted_at is None and rows["v3"].deleted_at is None
    sync.state["pages"] = [[video("v1"), video("v2")], [video("v3")]]
    sync.worker.metrics()
    assert posts(sync)["v2"].deleted_at is None


def test_incomplete_or_empty_listing_never_judges(sync):
    sync.worker.metrics()
    sync.state["pages"] = [[video("v1")], [video("v3")]]
    sync.state["fail_page"] = 1
    result = sync.worker.metrics()
    assert not result["ok"] and result["errors"] == [
        {"platform": "tiktok", "code": "tiktok_server_error"}
    ]
    assert posts(sync)["v2"].deleted_at is None
    sync.state.update(fail_page=None, pages=[[]])
    sync.worker.metrics()
    assert all(p.deleted_at is None for p in posts(sync).values())


def test_rate_limit_is_reported_as_tiktok_not_meta(sync):
    sync.state["status"] = 429
    result = sync.worker.metrics()
    assert not result["ok"] and result["errors"] == [
        {"platform": "tiktok", "code": "tiktok_rate_limited"}
    ]


def test_followers_are_recorded_once_a_day(sync):
    assert sync.worker.followers()["inserted"] == 1
    assert sync.worker.followers()["inserted"] == 0
    with sync.tt.factory() as session:
        assert [r.followers_count for r in session.scalars(select(FollowerSnapshot))] == [321]
    report = sync.tt.client.get("/api/posts/followers?platform=tiktok").json()
    assert report["connected"] and report["current_count"] == 321


def test_broken_link_skips_tiktok_without_calling_it(sync):
    with sync.tt.factory.begin() as session:
        row = oauth.connection(session, "tiktok")
        row.cache_json = {**row.cache_json, "reconnect": True}
    result = sync.worker.metrics()
    assert "tiktok" not in str(result.get("errors", []))
    assert sync.calls == []
    assert tiktok.account(sync.tt.factory, sync.tt.settings) is None


def test_rejected_token_is_reported(sync):
    sync.state["status"] = 401
    result = sync.worker.metrics()
    assert result["errors"] == [{"platform": "tiktok", "code": "tiktok_auth_error"}]
    assert utc_now()


def test_link_without_stats_still_syncs_videos_but_not_followers(sync):
    # TikTok 只回使用者同意的權限：缺 user.info.stats 時影片照常同步，粉絲數記錯誤、不呼叫。
    with sync.tt.factory.begin() as session:
        row = oauth.connection(session, "tiktok")
        row.granted_scopes = ["user.info.basic", "video.list", "video.upload"]
        row.credential_digest = oauth.digest_credentials(session, sync.tt.settings, "tiktok")
    result = sync.worker.metrics()
    assert result["ok"] and result["posts"] == 3
    followers = sync.worker.followers()
    assert followers["errors"] == [{"platform": "tiktok", "code": "tiktok_permission_missing"}]
    assert not [c for c in sync.calls if c[1] == tiktok.USER_URL]


def test_unexpected_tiktok_error_is_recorded_without_failing_the_job(sync, monkeypatch):
    def broken(self, result):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(tiktok.Sync, "sync", broken)
    result = sync.worker.metrics()
    assert result["errors"] == [{"platform": "tiktok", "code": "sync_failed"}]


def test_tiktok_only_brand_opens_the_tiktok_tab(sync):
    sync.worker.metrics()
    response = sync.tt.client.get("/api/posts/platforms")
    assert response.json()["default_platform"] == "tiktok"
