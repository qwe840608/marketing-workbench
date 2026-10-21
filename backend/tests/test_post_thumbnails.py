"""縮圖快取：全部以替身 HTTP 驗證，不連真實平台或 CDN。"""

import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import select
from test_classify import classified_data as classified_data

from app.models import Account, MetaApiCall, Post, PostThumbnail
from app.services import post_thumbnails
from app.services.publish_platforms import FB

NOW = datetime(2026, 12, 16, 12, tzinfo=UTC)


def image_bytes(size=(1200, 800), mode="RGB", fmt="JPEG"):
    output = io.BytesIO()
    Image.new(mode, size, (200, 30, 30, 128) if mode == "RGBA" else (200, 30, 30)).save(output, fmt)
    return output.getvalue()


class FakeHttp:
    def __init__(self):
        self.calls = []
        self.graph = {}
        self.files = {}
        self.fail = set()

    def __call__(self, url, *, headers=None, params=None):
        self.calls.append(url)
        if url in self.fail:
            raise ConnectionError("isolated failure")
        if url.startswith(FB + "/"):
            key = url.removeprefix(FB + "/")
            status, body = self.graph.get(key, (400, {"error": {"code": 100}}))
            assert headers["Authorization"] == "Bearer isolated-thumbnail-token"
            return status, json.dumps(body).encode()
        if url in self.files:
            return 200, self.files[url]
        return 404, b""


@pytest.fixture
def setup(client, classified_data, settings):
    settings.meta_page_access_token = SecretStr("isolated-thumbnail-token")
    factory = client.app.state.session_factory
    with factory.begin() as session:
        # 種子貼文不屬於這個測試；標成已刪除，排程不會挑到。
        for post in session.scalars(select(Post)):
            post.deleted_at = NOW
        brand = classified_data["brand_id"]
        accounts = {
            platform: Account(
                brand_id=brand, platform=platform, external_id=f"thumb-{platform}", name=platform
            )
            for platform in ("facebook", "instagram", "youtube", "line")
        }
        session.add_all(accounts.values())
        session.flush()
        posts = {}
        for index, (name, platform, external) in enumerate(
            [
                ("fb", "facebook", "111_222"),
                ("text", "facebook", "111_333"),
                ("gone", "facebook", "111_444"),
                ("ig", "instagram", "9001"),
                ("yt", "youtube", "abcDEF12345"),
                ("line", "line", "line-post"),
            ]
        ):
            posts[name] = Post(
                account_id=accounts[platform].id,
                external_id=external,
                caption=name,
                media_type="VIDEO" if name == "ig" else "IMAGE",
                published_at=NOW - timedelta(hours=index),
            )
        session.add_all(posts.values())
        session.flush()
        ids = {name: post.id for name, post in posts.items()}
    http = FakeHttp()
    http.graph = {
        "111_222": (200, {"full_picture": "https://scontent.xx.fbcdn.net/fb.jpg?sig=1"}),
        "111_333": (200, {"id": "111_333"}),
        "111_444": (400, {"error": {"code": 100}}),
        "9001": (
            200,
            {
                "media_type": "VIDEO",
                "media_url": "https://video.cdninstagram.com/clip.mp4",
                "thumbnail_url": "https://scontent.cdninstagram.com/cover.jpg",
            },
        ),
    }
    http.files = {
        "https://scontent.xx.fbcdn.net/fb.jpg?sig=1": image_bytes(),
        "https://scontent.cdninstagram.com/cover.jpg": image_bytes((300, 600)),
        "https://i.ytimg.com/vi/abcDEF12345/hqdefault.jpg": image_bytes((480, 360), "RGBA", "PNG"),
    }
    return factory, settings, http, ids


def rows(factory):
    with factory() as session:
        return {row.post_id: row for row in session.scalars(select(PostThumbnail))}


def test_hourly_caches_small_jpegs_and_marks_unavailable(setup):
    factory, settings, http, ids = setup
    assert post_thumbnails.hourly(factory, settings, get=http, now=NOW) == 3
    stored = rows(factory)
    assert ids["line"] not in stored
    for name in ("fb", "ig", "yt"):
        row = stored[ids[name]]
        assert row.status == "ready" and row.mime == "image/jpeg"
        assert max(row.width, row.height) <= post_thumbnails.SIDE
        with factory() as session:
            data = session.get(PostThumbnail, row.id).data
        with Image.open(io.BytesIO(data)) as image:
            assert image.format == "JPEG" and image.mode == "RGB"
    assert (stored[ids["ig"]].width, stored[ids["ig"]].height) == (240, 480)
    # 影片不下載 media_url（影片檔），只用封面。
    assert "https://video.cdninstagram.com/clip.mp4" not in http.calls
    assert stored[ids["text"]].status == "unavailable"
    assert stored[ids["text"]].error == "no_image"
    assert stored[ids["gone"]].status == "unavailable"
    with factory() as session:
        calls = list(session.scalars(select(MetaApiCall)))
    assert len(calls) == 4 and {c.source for c in calls} == {"metrics"}
    assert all(c.completed_at for c in calls)
    # 已有結果的貼文下一輪不再呼叫。
    http.calls.clear()
    assert post_thumbnails.hourly(factory, settings, get=http, now=NOW) == 0
    assert http.calls == []


def test_retry_backoff_then_gives_up(setup):
    factory, settings, http, ids = setup
    http.fail.add("https://scontent.xx.fbcdn.net/fb.jpg?sig=1")
    now = NOW
    for hours in post_thumbnails.RETRY_HOURS:
        post_thumbnails.hourly(factory, settings, get=http, now=now)
        row = rows(factory)[ids["fb"]]
        assert row.status == "retry" and row.error == "network_error"
        assert row.next_attempt_at == now + timedelta(hours=hours)
        http.calls.clear()
        post_thumbnails.hourly(factory, settings, get=http, now=now + timedelta(minutes=30))
        assert "111_222" not in " ".join(http.calls)
        now += timedelta(hours=hours)
    post_thumbnails.hourly(factory, settings, get=http, now=now)
    assert rows(factory)[ids["fb"]].status == "unavailable"


def test_untrusted_image_host_is_not_downloaded(setup):
    factory, settings, http, ids = setup
    http.graph["111_222"] = (200, {"full_picture": "https://attacker.example/fb.jpg"})
    post_thumbnails.hourly(factory, settings, get=http, now=NOW)
    row = rows(factory)[ids["fb"]]
    assert row.status == "unavailable" and row.error == "untrusted_host"
    assert "https://attacker.example/fb.jpg" not in http.calls


def test_meta_budget_pause_skips_meta_but_keeps_youtube(setup):
    from app.services import meta_api

    factory, settings, http, ids = setup
    with factory.begin() as session:
        meta_api.block(session, NOW, 3600)
    assert post_thumbnails.hourly(factory, settings, get=http, now=utc_now_close()) == 1
    stored = rows(factory)
    assert set(stored) == {ids["yt"]}
    assert not [c for c in http.calls if c.startswith(FB)]


def utc_now_close():
    from app.models.base import utc_now

    return utc_now()


def test_without_meta_token_only_youtube(setup):
    factory, settings, http, ids = setup
    settings.meta_page_access_token = None
    assert post_thumbnails.hourly(factory, settings, get=http, now=NOW) == 1
    assert set(rows(factory)) == {ids["yt"]}


def test_thumbnail_api_and_post_list(client, setup):
    factory, settings, http, ids = setup
    post_thumbnails.hourly(factory, settings, get=http, now=NOW)
    listed = {row["id"]: row for row in client.get("/api/posts?limit=200").json()}
    assert listed[ids["fb"]]["thumbnail_url"].startswith(f"/api/posts/{ids['fb']}/thumbnail?v=")
    assert listed[ids["text"]]["thumbnail_url"] is None
    single = client.get(f"/api/posts/{ids['yt']}").json()
    response = client.get(single["thumbnail_url"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    # 全站 API 一律 no-store；縮圖也不留在瀏覽器快取。
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/api/posts/{ids['text']}/thumbnail").status_code == 404
    assert client.get("/api/posts/999999/thumbnail").status_code == 404
    client.cookies.clear()
    assert client.get(single["thumbnail_url"]).status_code == 401


def test_dashboard_ranking_carries_thumbnail(client, setup, monkeypatch):
    from app.models import MetricSnapshot
    from app.services import dashboard

    factory, settings, http, ids = setup
    post_thumbnails.hourly(factory, settings, get=http, now=NOW)
    with factory.begin() as session:
        session.add(MetricSnapshot(post_id=ids["fb"], captured_at=NOW, reach=50))
    monkeypatch.setattr(dashboard, "utc_now", lambda: NOW + timedelta(minutes=1))
    value = client.get("/api/dashboard").json()
    assert value["highest_reach"][0]["thumbnail_url"].startswith(f"/api/posts/{ids['fb']}/")


class FakeTikTok:
    def __init__(self, videos=None, status=200, code="ok"):
        self.calls = []
        self.videos, self.status, self.code = videos or {}, status, code

    def __call__(self, url, *, headers=None, params=None, body=None):
        assert url == post_thumbnails.TIKTOK_QUERY_URL
        assert headers["Authorization"] == "Bearer isolated-tiktok-token"
        assert params == {"fields": "id,cover_image_url"}
        ids = body["filters"]["video_ids"]
        self.calls.append(ids)
        videos = [self.videos[i] for i in ids if i in self.videos]
        return self.status, json.dumps(
            {"data": {"videos": videos}, "error": {"code": self.code}}
        ).encode()


@pytest.fixture
def tiktok_setup(setup, monkeypatch):
    from app.services import tiktok, tiktok_oauth

    factory, settings, http, ids = setup
    with factory.begin() as session:
        for post in session.scalars(select(Post)):
            post.deleted_at = NOW
        brand = session.get(Account, session.get(Post, ids["fb"]).account_id).brand_id
        account = Account(brand_id=brand, platform="tiktok", external_id="thumb-tt", name="tt")
        session.add(account)
        session.flush()
        posts = [
            Post(
                account_id=account.id,
                external_id=external,
                caption=external,
                media_type="VIDEO",
                published_at=NOW - timedelta(hours=index),
            )
            for index, external in enumerate(("7400000000000000001", "7400000000000000002"))
        ]
        session.add_all(posts)
        session.flush()
        tt_ids = [post.id for post in posts]
    monkeypatch.setattr(tiktok, "account", lambda factory, settings: "thumb-tt")
    monkeypatch.setattr(tiktok_oauth, "access_token", lambda f, s: "isolated-tiktok-token")
    cover = "https://p16-sign-va.tiktokcdn.com/obj/cover~tplv-noop.image?x-expires=1"
    http.files[cover] = image_bytes((540, 960), fmt="WEBP")
    fake = FakeTikTok(
        {"7400000000000000001": {"id": "7400000000000000001", "cover_image_url": cover}}
    )
    return factory, settings, http, fake, tt_ids


def test_tiktok_cover_from_video_query(tiktok_setup):
    factory, settings, http, fake, tt_ids = tiktok_setup
    assert post_thumbnails.hourly(factory, settings, get=http, post=fake, now=NOW) == 1
    stored = rows(factory)
    assert stored[tt_ids[0]].status == "ready"
    assert (stored[tt_ids[0]].width, stored[tt_ids[0]].height) == (270, 480)
    # 不在 video/query 結果裡（已刪除或私人）就不再重試。
    assert stored[tt_ids[1]].status == "unavailable" and stored[tt_ids[1]].error == "not_found"
    assert fake.calls == [["7400000000000000001"], ["7400000000000000002"]]


def test_tiktok_rate_limit_pauses_without_spending_attempts(tiktok_setup):
    factory, settings, http, fake, tt_ids = tiktok_setup
    fake.status, fake.code = 429, "rate_limit_exceeded"
    assert post_thumbnails.hourly(factory, settings, get=http, post=fake, now=NOW) == 0
    assert len(fake.calls) == 1
    assert not set(rows(factory)) & set(tt_ids)


def test_tiktok_skipped_when_link_not_ready(tiktok_setup, monkeypatch):
    from app.services import tiktok

    factory, settings, http, fake, tt_ids = tiktok_setup
    monkeypatch.setattr(tiktok, "account", lambda factory, settings: None)
    post_thumbnails.hourly(factory, settings, get=http, post=fake, now=NOW)
    assert fake.calls == []
    assert not set(rows(factory)) & set(tt_ids)


def test_tiktok_unknown_cdn_host_retries(tiktok_setup):
    factory, settings, http, fake, tt_ids = tiktok_setup
    fake.videos["7400000000000000001"]["cover_image_url"] = "https://cdn.example/cover.jpg"
    post_thumbnails.hourly(factory, settings, get=http, post=fake, now=NOW)
    row = rows(factory)[tt_ids[0]]
    assert row.status == "retry" and row.error == "untrusted_host"
    assert "https://cdn.example/cover.jpg" not in http.calls
