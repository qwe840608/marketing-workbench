"""YouTube publishing contracts; every Google request uses MockTransport and synthetic media."""

import json
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from alembic import command
from alembic.config import Config
from conftest import login as shared_login
from cryptography.fernet import Fernet
from publish_http_mock import PlatformMock, jpeg_bytes, seed_connections, seed_youtube, video_bytes
from pydantic import SecretStr
from sqlalchemy import insert, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.config import REPO_ROOT
from app.models import (
    Account,
    AuditLog,
    Brand,
    PublishLink,
    PublishMedia,
    PublishPost,
    PublishTarget,
    Setting,
    Staff,
)
from app.models.base import utc_now
from app.services import (
    oauth,
    publish,
    publish_platforms,
    publish_presence,
    publish_rules,
    publish_youtube,
    youtube,
    youtube_oauth,
)
from app.services.gateway_workers import Workers
from app.services.passwords import hash_password

KB = 1024
UPLOAD = youtube_oauth.UPLOAD_SCOPES[0]


def build(client, settings, monkeypatch, *, upload=True):
    settings.account_encryption_key = SecretStr(Fernet.generate_key().decode())
    settings.webhook_public_url = "https://public.example.test/webhook/meta-inbound"
    settings.publish_poll_seconds = 0.01
    settings.publish_poll_timeout = 0.03
    mock = PlatformMock()
    monkeypatch.setattr(publish_platforms, "client_factory", mock.client)
    # 退避等待不實際睡眠；分段縮到協定允許的最小單位，小檔案也能測多段。
    monkeypatch.setattr(publish_youtube, "BACKOFF", (0,) * publish_youtube.RETRY_LIMIT)
    monkeypatch.setattr(publish_youtube, "CHUNK", 256 * KB)
    password = SecretStr("isolated-youtube-publish")
    factory = client.app.state.session_factory
    with factory.begin() as session:
        brand = Brand(slug="yt-publish", name="隔離品牌")
        staff = Staff(
            username="yt-publisher",
            display_name="隔離管理員",
            role="admin",
            password_hash=hash_password(password),
        )
        session.add_all([brand, staff])
        session.flush()
        seed_connections(session, settings, brand.id)
        seed_youtube(session, settings, brand.id, upload=upload)
        brand_id = brand.id
    client.headers.update(
        shared_login(client, "yt-publisher", password.get_secret_value(), origin=None)
    )
    switch = client.put("/api/publish/switch", json={"enabled": True, "confirmed": True})
    assert switch.status_code == 200
    return SimpleNamespace(
        client=client,
        brand=brand_id,
        mock=mock,
        google=mock.youtube,
        settings=settings,
        factory=factory,
    )


@pytest.fixture
def yt(client, settings, monkeypatch):
    return build(client, settings, monkeypatch)


@pytest.fixture
def yt_read_only(client, settings, monkeypatch):
    return build(client, settings, monkeypatch, upload=False)


def make(
    yt,
    *,
    format="video",
    platforms=("youtube",),
    caption="標題第一行\n\n說明內容 #標籤",
    options=None,
    captions=None,
    video=None,
    thumbnail=None,
):
    response = yt.client.post(
        "/api/publish/posts",
        json={
            "brand_id": yt.brand,
            "format": format,
            "platforms": list(platforms),
            "caption": caption,
            **({"captions": captions} if captions else {}),
            **({"platform_options": options} if options is not None else {}),
        },
    )
    assert response.status_code == 201, response.text
    post = response.json()
    if format != "text":
        content = video if video is not None else video_bytes(1920, 1080)
        if format == "image":
            content = jpeg_bytes()
        for _ in range(2 if format == "carousel" else 1):
            response = yt.client.post(
                f"/api/publish/posts/{post['id']}/media?filename=media.bin",
                content=content,
                headers={"Content-Type": "application/octet-stream"},
            )
            assert response.status_code == 200, response.text
            post = response.json()
    if thumbnail is not None:
        post = upload_thumbnail(yt, post, thumbnail)
    return post


def upload_thumbnail(yt, post, content, expected=200):
    response = yt.client.post(
        f"/api/publish/posts/{post['id']}/media?filename=thumb.jpg&role=thumbnail",
        content=content,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == expected, response.text
    return response.json() if expected == 200 else post


def submit(yt, post, endpoint="submit", when=None):
    return yt.client.post(
        f"/api/publish/posts/{post['id']}/{endpoint}",
        json={
            "confirmed": True,
            "version": post["version"],
            "scheduled_at": when.isoformat() if when else None,
        },
    )


def fresh(yt, post):
    return yt.client.get(f"/api/publish/posts/{post['id']}").json()


def target(yt, post, platform="youtube"):
    with yt.factory() as session:
        return next(t for t in publish.targets(session, post["id"]) if t.platform == platform)


def checks(yt, post):
    response = yt.client.post(f"/api/publish/posts/{post['id']}/check")
    assert response.status_code == 200, response.text
    return response.json()


def starts(yt):
    return [c for c in yt.google.calls if c[0] == "POST" and c[1].endswith("/videos")]


def puts(yt):
    return [c for c in yt.google.calls if c[0] == "PUT"]


def thumbnails(yt):
    return [c for c in yt.google.calls if c[1].endswith("/thumbnails/set")]


def video_calls(yt):
    return [c for c in yt.google.calls if not c[1].endswith("/thumbnails/set")]


def padded(size, **kwargs):
    return video_bytes(1920, 1080, padding=size, **kwargs)


def test_resumable_upload_streams_chunks_and_records_the_video(yt):
    content = padded(600 * KB)
    post = make(yt, video=content, thumbnail=jpeg_bytes(1280, 720))
    response = submit(yt, post)
    assert response.status_code == 200, response.text
    assert fresh(yt, post)["status"] == "done"
    identity = yt.google.completed[0]["id"]
    row = target(yt, post)
    assert (row.status, row.platform_post_id) == ("succeeded", identity)
    assert row.permalink == "https://www.youtube.com/watch?v=" + identity
    # 初始化：官方參數與標頭，影片位元組不經過公開媒體連結。
    method, path, params, headers, _ = yt.google.calls[0]
    assert (method, path) == ("POST", "/upload/youtube/v3/videos")
    assert params == {"uploadType": "resumable", "part": "snippet,status"}
    assert headers["authorization"] == "Bearer isolated-youtube-access"
    assert headers["x-upload-content-type"] == "video/mp4"
    assert headers["x-upload-content-length"] == str(len(content))
    assert headers["content-type"] == "application/json; charset=UTF-8"
    # 分段：Content-Range 連續、非最後一段為 256 KiB 的整數倍、位元組總數等於檔案大小。
    total = len(content)
    ranges = [c[3]["content-range"] for c in puts(yt)]
    assert ranges == [
        f"bytes 0-{256 * KB - 1}/{total}",
        f"bytes {256 * KB}-{512 * KB - 1}/{total}",
        f"bytes {512 * KB}-{total - 1}/{total}",
    ]
    assert sum(c[4] for c in puts(yt)) == total
    # 縮圖在影片完成後才另外送出，且只送一次。
    assert [c[1] for c in yt.google.calls][-1] == "/upload/youtube/v3/thumbnails/set"
    assert thumbnails(yt)[0][2]["videoId"] == identity
    with yt.factory() as session:
        assert not list(session.scalars(select(PublishLink)))
        assert session.scalar(select(Setting).where(Setting.key == "youtube.uploads")).value_json[
            "used"
        ] == 1


def test_snippet_and_status_fields(yt):
    post = make(
        yt,
        caption="預設標題\n\n說明第二段",
        options={
            "youtube": {"title": "  自訂標題  ", "privacy": "unlisted", "made_for_kids": True}
        },
    )
    assert submit(yt, post).status_code == 200
    body = yt.google.sessions["mockupload1"]["metadata"]
    assert body == {
        "snippet": {
            "title": "自訂標題",
            "description": "預設標題\n\n說明第二段",
            "categoryId": "22",
        },
        "status": {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": True},
    }


def test_default_title_privacy_kids_and_platform_caption_and_category_setting(yt):
    changed = yt.client.put("/api/oauth/youtube/category", json={"category_id": "27"})
    assert changed.status_code == 200 and changed.json() == {"category_id": "27"}
    invalid = yt.client.put("/api/oauth/youtube/category", json={"category_id": "999"})
    assert invalid.status_code == 422
    status = yt.client.get("/api/oauth/status").json()["platforms"]["youtube"]
    assert status["category_id"] == "27"
    post = make(
        yt,
        caption="共用文案\n\n共用內容",
        captions={"youtube": "\n  YouTube 專屬第一行\n其餘說明"},
    )
    assert post["platform_options"]["youtube"] == {
        "title": "",
        "privacy": "public",
        "made_for_kids": False,
        "thumbnail_media_id": None,
    }
    assert submit(yt, post).status_code == 200
    body = yt.google.sessions["mockupload1"]["metadata"]
    # 標題空白沿用 YouTube 說明的第一個非空行；說明沿用平台文案機制；類別來自設定。
    assert body["snippet"] == {
        "title": "YouTube 專屬第一行",
        "description": "\n  YouTube 專屬第一行\n其餘說明",
        "categoryId": "27",
    }
    assert body["status"] == {"privacyStatus": "public", "selfDeclaredMadeForKids": False}


def test_category_setting_is_admin_only_and_defaults_to_people_and_blogs(yt):
    assert youtube_oauth.CATEGORIES[youtube_oauth.DEFAULT_CATEGORY] == "人物與網誌"
    assert yt.client.get("/api/oauth/status").json()["platforms"]["youtube"]["category_id"] == "22"
    with yt.factory.begin() as session:
        session.scalar(select(Staff).where(Staff.username == "yt-publisher")).role = "marketing"
    denied = yt.client.put("/api/oauth/youtube/category", json={"category_id": "27"})
    assert denied.status_code == 403


@pytest.mark.parametrize(
    "title,description,reason",
    [
        ("字" * 100, "a" * 5000, None),
        ("字" * 101, "ok", "標題最多 100 字"),
        ("", "", "標題必填"),
        ("標題", "字" * 1667, "說明最多 5,000 位元組"),
        ("標題", "字" * 1666 + "ab", None),
        ("標題", "a" * 5001, "說明最多 5,000 位元組"),
    ],
)
def test_title_and_description_limits(yt, title, description, reason):
    post = make(yt, caption=description, options={"youtube": {"title": title}})
    result = checks(yt, post)["youtube"]
    if reason is None:
        assert result["ok"] and not result["reasons"]
        assert submit(yt, post).status_code == 200
    else:
        assert not result["ok"] and any(reason in item for item in result["reasons"])
        rejected = submit(yt, post)
        assert rejected.status_code == 422 and reason in rejected.json()["detail"]
        assert not yt.google.calls


@pytest.mark.parametrize("format", ["image", "text", "carousel"])
def test_only_video_can_be_posted_to_youtube(yt, format):
    post = make(yt, format=format)
    result = checks(yt, post)["youtube"]
    assert not result["ok"] and not result["supported"]
    assert "YouTube：YouTube 只支援影片" in result["reasons"]
    rejected = submit(yt, post)
    assert rejected.status_code == 422 and "YouTube 只支援影片" in rejected.json()["detail"]
    assert not yt.google.calls
    # 其他平台不受影響：同一篇圖片貼文仍可發佈到 Facebook。
    if format == "image":
        assert checks(yt, post)["facebook"]["ok"]


def test_story_cannot_target_youtube(yt):
    response = yt.client.post(
        "/api/publish/posts",
        json={"brand_id": yt.brand, "format": "story", "platforms": ["youtube"]},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "size,duration,short",
    [
        ((1080, 1920), 12, True),
        ((1080, 1080), 12, True),
        ((1080, 1920), 180, True),
        ((1080, 1920), 181, False),
        ((1920, 1080), 12, False),
    ],
)
def test_shorts_notice_and_thumbnail_rule(yt, size, duration, short):
    post = make(yt, video=video_bytes(*size, duration=duration))
    result = checks(yt, post)["youtube"]
    assert result["ok"]
    assert any("Shorts" in item for item in result["warnings"]) is short
    post = upload_thumbnail(yt, post, jpeg_bytes(1280, 720))
    result = checks(yt, post)["youtube"]
    # Shorts 不支援自訂縮圖（YouTube 說明：只能在電腦版 Studio 加入），帶縮圖就擋下並說明原因。
    assert result["ok"] is not short
    assert any("Shorts 不支援自訂縮圖" in item for item in result["reasons"]) is short


def test_thumbnail_rules_are_notes_for_ratio_and_blocks_for_format_and_size(yt):
    post = make(yt, thumbnail=jpeg_bytes(1000, 1000))
    result = checks(yt, post)["youtube"]
    assert result["ok"] and "縮圖建議 16:9（1280×720 以上）" in result["warnings"]
    post = upload_thumbnail(yt, post, jpeg_bytes(1280, 720))
    assert checks(yt, post)["youtube"]["warnings"] == []
    post = upload_thumbnail(yt, post, jpeg_bytes(320, 180))
    assert any("寬度建議至少 640" in w for w in checks(yt, post)["youtube"]["warnings"])
    # 縮圖只收 JPG／PNG、2 MB 內；影片檔或過大的圖不能當縮圖。
    upload_thumbnail(yt, post, video_bytes(), expected=422)
    big = jpeg_bytes(1280, 720) + b"0" * (2 * 1024**2)
    upload_thumbnail(yt, post, big, expected=413)
    assert publish_rules.RULES["youtube"]["thumbnail_bytes"] == 2 * 1024**2
    fine = jpeg_bytes(1280, 720) + b"0" * (2 * 1024**2 - len(jpeg_bytes(1280, 720)))
    assert upload_thumbnail(yt, post, fine)["thumbnail"]["size"] == 2 * 1024**2


def test_thumbnail_is_not_publish_media_and_can_be_replaced_removed_previewed(yt):
    post = make(
        yt,
        platforms=("youtube", "threads", "facebook"),
        options={"facebook": {"video_format": "feed"}},
        thumbnail=jpeg_bytes(1280, 720),
    )
    assert len(post["media"]) == 1 and post["media"][0]["mime"] == "video/mp4"
    thumbnail = post["thumbnail"]
    assert thumbnail["mime"] == "image/jpeg" and thumbnail["name"] == "thumb.jpg"
    assert post["platform_options"]["youtube"]["thumbnail_media_id"] == thumbnail["id"]
    # 其他平台的規則與素材清單看不到縮圖：影片格式仍只需一個媒體檔。
    result = checks(yt, post)
    assert result["facebook"]["ok"] and result["threads"]["ok"] and result["youtube"]["ok"]
    with yt.factory() as session:
        assert [m.id for m in publish.media_rows(session, post["id"])] == [post["media"][0]["id"]]
        old_path = stored_path(yt, session, thumbnail["id"])
    preview = yt.client.get(f"/api/publish/posts/{post['id']}/media/{thumbnail['id']}")
    assert preview.status_code == 200 and preview.headers["content-type"] == "image/jpeg"
    # 重新排序只需帶一般素材，縮圖不在 media_ids 內也能儲存。
    saved = yt.client.put(
        f"/api/publish/posts/{post['id']}",
        json={
            "brand_id": yt.brand,
            "format": "video",
            "caption": post["caption"],
            "platforms": post["platforms"],
            "media_ids": [post["media"][0]["id"]],
            "version": post["version"],
        },
    )
    assert saved.status_code == 200
    assert saved.json()["platform_options"]["youtube"]["thumbnail_media_id"] == thumbnail["id"]
    replaced = upload_thumbnail(yt, saved.json(), jpeg_bytes(1920, 1080))
    assert replaced["thumbnail"]["id"] != thumbnail["id"]
    assert not old_path.exists()
    stale = replaced["thumbnail"]["id"]
    removed = yt.client.delete(f"/api/publish/posts/{post['id']}/media/{stale}")
    assert removed.status_code == 200
    assert removed.json()["thumbnail"] is None
    assert removed.json()["platform_options"]["youtube"]["thumbnail_media_id"] is None
    # 發佈到 Threads 時只建立影片的公開連結，縮圖不會被當成素材送出。
    assert submit(yt, removed.json()).status_code == 200
    with yt.factory() as session:
        assert len(list(session.scalars(select(PublishLink)))) == 1


def stored_path(yt, session, identity):
    from app.services.publish_media import path_for

    return path_for(yt.settings, session.get(PublishMedia, identity))


def test_thumbnail_only_applies_to_video_posts(yt):
    post = make(yt, format="image")
    upload_thumbnail(yt, post, jpeg_bytes(1280, 720), expected=422)


def test_thumbnail_failure_does_not_fail_the_video_and_can_be_reapplied(yt):
    yt.google.thumbnail_error = (403, "forbidden")
    post = make(yt, thumbnail=jpeg_bytes(1280, 720))
    response = submit(yt, post)
    assert response.status_code == 200
    done = fresh(yt, post)
    assert done["status"] == "done"
    youtube_target = done["targets"][0]
    assert youtube_target["status"] == "succeeded" and youtube_target["permalink"]
    detail = youtube_target["detail"]
    assert detail["thumbnail"]["status"] == "failed" and detail["thumbnail"]["code"] == "forbidden"
    assert "電話驗證" in detail["thumbnail"]["reason"]
    assert "upload" not in detail
    uploads_before = len(video_calls(yt))
    # 仍然失敗：只有縮圖請求，沒有任何影片請求。
    again = yt.client.post(
        f"/api/publish/posts/{post['id']}/youtube-thumbnail", json={"confirmed": True}
    )
    assert again.status_code == 200
    assert again.json()["targets"][0]["detail"]["thumbnail"]["status"] == "failed"
    assert len(video_calls(yt)) == uploads_before and len(thumbnails(yt)) == 2
    yt.google.thumbnail_error = None
    fixed = yt.client.post(
        f"/api/publish/posts/{post['id']}/youtube-thumbnail", json={"confirmed": True}
    )
    assert fixed.status_code == 200
    assert fixed.json()["targets"][0]["detail"]["thumbnail"] == {"status": "applied"}
    assert len(video_calls(yt)) == uploads_before and len(thumbnails(yt)) == 3
    assert len(yt.google.completed) == 1
    with yt.factory() as session:
        logs = list(
            session.scalars(select(AuditLog).where(AuditLog.action == "publish.youtube.thumbnail"))
        )
        assert [log.detail_json["status"] for log in logs] == ["failed", "applied"]
    # 已套用就沒有可重新套用的縮圖。
    assert (
        yt.client.post(
            f"/api/publish/posts/{post['id']}/youtube-thumbnail", json={"confirmed": True}
        ).status_code
        == 409
    )


@pytest.mark.parametrize(
    "error,code",
    [
        ((400, "invalidImage"), "invalid_image"),
        ((429, "uploadRateLimitExceeded"), "rate_limited"),
        ((404, "videoNotFound"), "not_found"),
        ((401, "authError"), "token_invalid"),
        ((403, "quotaExceeded"), "quota_exceeded"),
        ((500, "backendError"), "unknown"),
    ],
)
def test_thumbnail_failure_reasons_are_distinguished(yt, error, code):
    yt.google.thumbnail_error = error
    post = make(yt, thumbnail=jpeg_bytes(1280, 720))
    assert submit(yt, post).status_code == 200
    detail = fresh(yt, post)["targets"][0]["detail"]["thumbnail"]
    assert detail["code"] == code
    assert detail["reason"] == publish_rules.THUMBNAIL_ERRORS[code]


def test_reapply_requires_failed_thumbnail_enabled_switch_and_live_video(yt):
    yt.google.thumbnail_error = (403, "forbidden")
    post = make(yt, thumbnail=jpeg_bytes(1280, 720))
    submit(yt, post)
    url = f"/api/publish/posts/{post['id']}/youtube-thumbnail"
    assert yt.client.post(url, json={}).status_code == 422
    with yt.factory.begin() as session:
        session.scalar(
            select(Setting).where(Setting.key == "publishing.enabled")
        ).value_json = {"enabled": False}
    assert yt.client.post(url, json={"confirmed": True}).status_code == 409
    with yt.factory.begin() as session:
        session.scalar(
            select(Setting).where(Setting.key == "publishing.enabled")
        ).value_json = {"enabled": True}
        row = session.scalar(select(PublishTarget).where(PublishTarget.post_id == post["id"]))
        row.deleted_at = utc_now()
    assert yt.client.post(url, json={"confirmed": True}).status_code == 409
    # 沒有縮圖的影片沒有可重新套用的內容。
    plain = make(yt)
    submit(yt, plain)
    assert (
        yt.client.post(
            f"/api/publish/posts/{plain['id']}/youtube-thumbnail", json={"confirmed": True}
        ).status_code
        == 409
    )


def test_thumbnail_quota_is_reserved_and_never_fails_the_video(yt):
    from app.services.youtube import DAILY_LIMIT, PACIFIC

    day = utc_now().astimezone(PACIFIC).date().isoformat()
    with yt.factory.begin() as session:
        session.add(
            Setting(key="youtube.quota", value_json={"day": day, "used": DAILY_LIMIT - 10})
        )
    post = make(yt, thumbnail=jpeg_bytes(1280, 720))
    assert submit(yt, post).status_code == 200
    done = fresh(yt, post)
    assert done["status"] == "done"
    assert done["targets"][0]["detail"]["thumbnail"]["code"] == "quota_exceeded"
    assert not thumbnails(yt)


def test_missing_upload_scope_blocks_publishing_but_not_reads(yt_read_only):
    yt = yt_read_only
    status = yt.client.get("/api/oauth/status").json()["platforms"]["youtube"]
    # 既有連結只缺上傳範圍：狀態仍為已連結，缺口列在 data_missing（比照 Threads）。
    assert status["state"] == "ready" and status["missing"] == []
    assert status["data_missing"] == [UPLOAD]
    options = yt.client.get(f"/api/publish/options?brand_id={yt.brand}").json()
    youtube_option = options["platforms"]["youtube"]
    assert not youtube_option["ready"]
    assert youtube_option["hint"] == "需要重新連結以取得上傳權限"
    assert "需要重新連結以取得上傳權限" in youtube_option["reasons"]
    assert options["platforms"]["facebook"]["ready"]
    post = make(yt)
    result = checks(yt, post)["youtube"]
    assert not result["ok"] and "需要重新連結以取得上傳權限" in result["reasons"]
    rejected = submit(yt, post)
    assert rejected.status_code == 422 and "需要重新連結以取得上傳權限" in rejected.json()["detail"]
    assert not yt.google.calls
    # 讀取不受影響：換發權杖與頻道讀取帳號照常可用。
    assert youtube_oauth.access_token(yt.factory, yt.settings) == "isolated-youtube-access"
    assert youtube.account(yt.factory, yt.settings) == "UC_isolated_channel"


def test_unlinked_or_failed_youtube_is_not_ready(yt):
    with yt.factory.begin() as session:
        oauth.connection(session, "youtube").cache_json = {"reconnect": True}
    options = yt.client.get(f"/api/publish/options?brand_id={yt.brand}").json()
    assert not options["platforms"]["youtube"]["ready"]
    assert "hint" not in options["platforms"]["youtube"]
    assert "授權無效，請重新連結帳號" in options["platforms"]["youtube"]["reasons"]
    with yt.factory.begin() as session:
        session.execute(
            Account.__table__.update()
            .where(Account.platform == "youtube")
            .values(external_id="UC_other_channel")
        )
    options = yt.client.get(f"/api/publish/options?brand_id={yt.brand}").json()
    assert options["platforms"]["youtube"]["name"] == "未連結"


def test_scheduled_publish_uploads_only_when_due(yt):
    post = make(yt, options={"youtube": {"privacy": "private"}})
    when = utc_now() + timedelta(minutes=10)
    assert submit(yt, post, when=when).status_code == 200
    assert fresh(yt, post)["status"] == "scheduled" and not yt.google.calls
    factory = yt.factory
    publish.tick(factory, yt.settings, when - timedelta(minutes=5), wait=True)
    assert not yt.google.calls
    publish.tick(factory, yt.settings, when + timedelta(seconds=1), wait=True)
    assert fresh(yt, post)["status"] == "done"
    assert yt.google.sessions["mockupload1"]["metadata"]["status"]["privacyStatus"] == "private"
    assert len(yt.google.completed) == 1


def test_all_platforms_publish_together_and_retry_never_reuploads_succeeded_video(yt):
    feed = {"facebook": {"video_format": "feed"}}
    post = make(yt, platforms=("facebook", "youtube"), options=feed)
    yt.mock.fail_facebook = True
    assert submit(yt, post).status_code == 200
    partial = fresh(yt, post)
    assert partial["status"] == "partial"
    states = {t["platform"]: t["status"] for t in partial["targets"]}
    assert states == {"facebook": "failed", "youtube": "succeeded"}
    google_before = len(yt.google.calls)
    yt.mock.fail_facebook = False
    assert submit(yt, partial, "retry").status_code == 200
    assert fresh(yt, post)["status"] == "done"
    assert len(yt.google.calls) == google_before and len(yt.google.completed) == 1
    assert target(yt, post).attempts == 1


def test_interrupted_connection_resumes_from_the_confirmed_offset(yt):
    yt.google.faults = ["drop"]
    content = padded(600 * KB)
    post = make(yt, video=content)
    assert submit(yt, post).status_code == 200
    assert fresh(yt, post)["status"] == "done"
    total = len(content)
    ranges = [c[3]["content-range"] for c in puts(yt)]
    # 第一段送達但回應中斷：先詢問伺服器收到多少，再從第二段續傳，不重送第一段。
    assert ranges == [
        f"bytes 0-{256 * KB - 1}/{total}",
        f"bytes */{total}",
        f"bytes {256 * KB}-{512 * KB - 1}/{total}",
        f"bytes {512 * KB}-{total - 1}/{total}",
    ]
    assert len(starts(yt)) == 1 and len(yt.google.completed) == 1


def test_temporary_server_error_retries_with_status_query(yt):
    yt.google.faults = ["503", "503"]
    content = padded(300 * KB)
    post = make(yt, video=content)
    assert submit(yt, post).status_code == 200
    assert fresh(yt, post)["status"] == "done"
    total = len(content)
    ranges = [c[3]["content-range"] for c in puts(yt)]
    assert ranges.count(f"bytes */{total}") == 2
    assert ranges.count(f"bytes 0-{256 * KB - 1}/{total}") == 3
    assert len(yt.google.completed) == 1


def test_persistent_failure_is_safe_and_a_retry_resumes_the_saved_session(yt):
    yt.google.faults = ["503"] * 20
    content = padded(600 * KB)
    post = make(yt, video=content)
    assert submit(yt, post).status_code == 200
    failed = fresh(yt, post)
    assert failed["status"] == "failed"
    row = failed["targets"][0]
    assert row["status"] == "failed" and row["reason"] == publish_rules.ERRORS["timeout"]
    # 工作階段網址只存在伺服端，不回給瀏覽器。
    assert "upload" not in row["detail"] and "mockupload" not in json.dumps(failed)
    assert not yt.google.completed
    assert "mockupload1" in json.dumps(target(yt, post).detail_json)
    yt.google.faults = []
    before = len(yt.google.calls)
    assert submit(yt, failed, "retry").status_code == 200
    assert fresh(yt, post)["status"] == "done"
    new_calls = yt.google.calls[before:]
    # 續傳：先問狀態再送剩餘位元組；沒有重新建立工作階段，也只有一支影片。
    assert not [c for c in new_calls if c[0] == "POST"]
    assert new_calls[0][3]["content-range"] == f"bytes */{len(content)}"
    assert len(yt.google.completed) == 1 and len(starts(yt)) == 1


def test_expired_session_restarts_once_then_fails_safely(yt):
    yt.google.faults = ["404"]
    post = make(yt, video=padded(300 * KB))
    assert submit(yt, post).status_code == 200
    assert fresh(yt, post)["status"] == "done"
    assert len(starts(yt)) == 2 and len(yt.google.completed) == 1
    second = make(yt, video=padded(300 * KB))
    yt.google.faults = ["404", "404"]
    assert submit(yt, second).status_code == 200
    assert fresh(yt, second)["targets"][0]["status"] == "failed"
    assert len(yt.google.completed) == 1


def test_permanent_media_rejection_does_not_retry(yt):
    yt.google.faults = ["400"]
    post = make(yt, video=padded(300 * KB))
    assert submit(yt, post).status_code == 200
    row = fresh(yt, post)["targets"][0]
    assert row["status"] == "failed" and row["reason"] == publish_rules.ERRORS["media_rejected"]
    assert len(puts(yt)) == 1


@pytest.mark.parametrize(
    "error,code",
    [
        ((401, "authError"), "token_invalid"),
        ((403, "forbidden"), "permission_missing"),
        ((403, "quotaExceeded"), "quota_exceeded"),
        ((400, "uploadLimitExceeded"), "quota_exceeded"),
        ((400, "invalidTitle"), "metadata_rejected"),
        ((400, "invalidDescription"), "metadata_rejected"),
        ((429, "rateLimitExceeded"), "rate_limited"),
    ],
)
def test_session_start_errors_map_to_safe_failures(yt, error, code):
    yt.google.start_error = error
    post = make(yt)
    assert submit(yt, post).status_code == 200
    row = fresh(yt, post)["targets"][0]
    assert row["status"] == "failed" and row["reason"] == publish_rules.ERRORS[code]
    assert target(yt, post).error_code == code
    assert not puts(yt) and not yt.google.completed
    # 錯誤文字（含平台原始訊息）不進發佈紀錄。
    assert "mockupload" not in json.dumps(row)


def test_session_start_server_error_gives_up_without_uploading(yt):
    yt.google.start_error = (503, "backendError")
    post = make(yt)
    assert submit(yt, post).status_code == 200
    assert target(yt, post).error_code == "unknown"
    assert len(starts(yt)) == publish_youtube.RETRY_LIMIT + 1 and not puts(yt)


def test_upload_session_url_must_be_the_official_endpoint(yt, monkeypatch):
    original = yt.google.handle

    def evil(request):
        response = original(request)
        if request.method == "POST" and request.url.path.endswith("/videos"):
            return httpx.Response(200, headers={"location": "https://evil.example.test/upload"})
        return response

    yt.google.handle = evil
    post = make(yt)
    assert submit(yt, post).status_code == 200
    assert target(yt, post).error_code == "unknown"
    assert not [c for c in yt.mock.calls if c[1] == "evil.example.test"]


def test_daily_upload_limit_is_enforced_before_any_request(yt):
    from app.services.youtube import PACIFIC

    day = utc_now().astimezone(PACIFIC).date().isoformat()
    with yt.factory.begin() as session:
        session.add(Setting(key="youtube.uploads", value_json={"day": day, "used": 100}))
    post = make(yt)
    assert submit(yt, post).status_code == 200
    assert target(yt, post).error_code == "quota_exceeded"
    assert not yt.google.calls
    # 隔天重新計算。
    with yt.factory.begin() as session:
        row = session.scalar(select(Setting).where(Setting.key == "youtube.uploads"))
        row.value_json = {"day": "2000-01-01", "used": 100}
    assert submit(yt, fresh(yt, post), "retry").status_code == 200
    assert fresh(yt, post)["status"] == "done"


def test_expired_access_token_is_refreshed_before_upload(yt, monkeypatch):
    with yt.factory.begin() as session:
        oauth.connection(session, "youtube").expires_at = utc_now() - timedelta(seconds=1)
    seen = []

    def refresh(url, **kwargs):
        seen.append(url)
        return {"access_token": "isolated-refreshed-token", "expires_in": 3600}

    monkeypatch.setattr(youtube_oauth, "request", refresh)
    post = make(yt)
    assert submit(yt, post).status_code == 200
    assert seen == [youtube_oauth.TOKEN_URL]
    assert yt.google.calls[0][3]["authorization"] == "Bearer isolated-refreshed-token"


def test_invalid_refresh_token_fails_the_target_and_asks_to_reconnect(yt, monkeypatch):
    with yt.factory.begin() as session:
        oauth.connection(session, "youtube").expires_at = utc_now() - timedelta(seconds=1)

    def refuse(url, **kwargs):
        raise oauth.ProviderFailure({"invalid_grant": True})

    monkeypatch.setattr(youtube_oauth, "request", refuse)
    post = make(yt)
    assert submit(yt, post).status_code == 200
    assert target(yt, post).error_code == "token_invalid"
    assert not yt.google.calls
    with yt.factory() as session:
        assert oauth.connection(session, "youtube").cache_json["reconnect"] is True


def test_published_target_records_the_video_before_the_thumbnail_step(yt):
    """影片編號先持久化：縮圖步驟中斷也不會讓重試重傳影片。"""
    post = make(yt, thumbnail=jpeg_bytes(1280, 720))
    original = publish_youtube.apply_thumbnail
    seen = {}

    def crash(settings, token, identifier, thumbnail):
        with yt.factory() as session:
            row = next(t for t in publish.targets(session, post["id"]) if t.platform == "youtube")
            seen["detail"], seen["id"] = dict(row.detail_json), row.platform_post_id
        raise publish_platforms.PlatformFailure("interrupted")

    publish_youtube.apply_thumbnail = crash
    try:
        assert submit(yt, post).status_code == 200
    finally:
        publish_youtube.apply_thumbnail = original
    # YouTube 回報的實際公開狀態與影片編號一起先持久化。
    assert seen["id"] == yt.google.completed[0]["id"]
    assert seen["detail"] == {"video_id": seen["id"], "privacy_status": "public"}
    row = fresh(yt, post)["targets"][0]
    # 縮圖例外被收斂成縮圖失敗，影片目標仍是成功。
    assert row["status"] == "succeeded" and row["detail"]["thumbnail"]["status"] == "failed"
    assert len(yt.google.completed) == 1


def test_actual_privacy_reported_by_youtube_is_kept_for_the_record(yt):
    yt.google.forced_privacy = "private"
    post = make(yt, options={"youtube": {"privacy": "public"}})
    assert submit(yt, post).status_code == 200
    done = fresh(yt, post)
    # 請求是公開，YouTube 實際設為私人（例如應用程式未通過稽核）：發佈仍成功，並保留實際狀態。
    assert done["status"] == "done" and done["targets"][0]["detail"]["privacy_status"] == "private"
    assert done["platform_options"]["youtube"]["privacy"] == "public"


def test_interrupted_target_with_saved_video_only_retries_the_thumbnail(yt):
    post = make(yt, thumbnail=jpeg_bytes(1280, 720))
    assert submit(yt, post).status_code == 200
    video = yt.google.completed[0]["id"]
    # 模擬程序在縮圖步驟後、狀態寫回前中斷：目標被標為 interrupted，但影片編號已保存。
    with yt.factory.begin() as session:
        row = session.scalar(select(PublishTarget).where(PublishTarget.post_id == post["id"]))
        row.status, row.error_code = "failed", "interrupted"
        row.detail_json = {"video_id": video}
        session.get(PublishPost, post["id"]).status = "failed"
    # 重新排程再取消會回到草稿；影片已建立時選項仍不能再改（改了也不會套用到那支影片）。
    with yt.factory.begin() as session:
        session.get(PublishPost, post["id"]).status = "draft"
    current = fresh(yt, post)
    changed = yt.client.put(
        f"/api/publish/posts/{post['id']}",
        json={
            "brand_id": yt.brand,
            "format": "video",
            "caption": current["caption"],
            "platforms": ["youtube"],
            "media_ids": [m["id"] for m in current["media"]],
            "platform_options": {"youtube": {"title": "改過的標題"}},
            "version": current["version"],
        },
    )
    assert changed.status_code == 409 and "YouTube" in changed.json()["detail"]
    with yt.factory.begin() as session:
        session.get(PublishPost, post["id"]).status = "failed"
    before = len(video_calls(yt))
    assert submit(yt, fresh(yt, post), "retry").status_code == 200
    assert len(video_calls(yt)) == before and len(yt.google.completed) == 1
    row = target(yt, post)
    assert row.status == "succeeded" and row.platform_post_id == video
    assert row.detail_json == {"video_id": video, "thumbnail": {"status": "applied"}}


# ---- 已刪除偵測：以 uploads 清單判定，重用完整清單 ----


def uploads_api(pages, *, fail_at=None, broken=None):
    calls = []

    def request(method, url, *, headers=None, qs=None, **kwargs):
        edge = url.rsplit("/", 1)[-1]
        calls.append((edge, dict(qs)))
        if edge == "channels":
            body = {
                "items": [
                    {
                        "id": "UC_isolated_channel",
                        "contentDetails": {"relatedPlaylists": {"uploads": "UU_isolated"}},
                        "statistics": {"subscriberCount": "10"},
                    }
                ]
            }
        elif edge == "playlistItems":
            page = int(qs.get("pageToken", "0"))
            if fail_at == page:
                return {"statusCode": 503, "body": {}, "headers": {}}
            body = {"items": [{"contentDetails": {"videoId": v}} for v in pages[page]]}
            if page + 1 < len(pages):
                body["nextPageToken"] = str(page + 1)
            if broken == "loop":
                body["nextPageToken"] = qs.get("pageToken", "") or "0"
        elif edge == "videos":
            body = {
                "items": [
                    {
                        "id": value,
                        "snippet": {
                            "channelId": "UC_isolated_channel",
                            "title": "t",
                            "publishedAt": (utc_now() - timedelta(days=1)).isoformat(),
                        },
                        "contentDetails": {"duration": "PT4M"},
                        "statistics": {},
                    }
                    for value in qs["id"].split(",")
                ]
            }
        else:
            body = {"columnHeaders": [], "rows": []}
        return {"statusCode": 200, "body": body, "headers": {}}

    request.calls = calls
    return request


def seed_youtube_video(yt, identity, *, minutes=30):
    post = make(yt)
    assert submit(yt, post).status_code == 200
    with yt.factory.begin() as session:
        row = session.scalar(select(PublishTarget).where(PublishTarget.post_id == post["id"]))
        row.platform_post_id = identity
        row.last_attempt_at = utc_now() - timedelta(minutes=minutes)
    return post


def presence(yt, api):
    workers = Workers(yt.factory, yt.settings, request=api)
    return publish_presence.run(
        yt.factory, yt.settings, platforms=("youtube",), workers=workers
    )


def deleted(yt, post):
    return target(yt, post).deleted_at


def test_presence_uses_the_full_uploads_list_including_other_pages(yt):
    gone = seed_youtube_video(yt, "vid_gone")
    kept = seed_youtube_video(yt, "vid_kept")
    result = presence(yt, uploads_api([["other_a"], ["vid_kept", "other_b"]]))
    assert result["checked"] == 2 and result["newly_deleted"] == 1 and not result["unresolved"]
    assert deleted(yt, gone) and not deleted(yt, kept)
    # 重新出現時還原。
    result = presence(yt, uploads_api([["vid_gone", "vid_kept"]]))
    assert result["restored"] == 1 and not deleted(yt, gone)


def test_presence_is_not_judged_for_empty_list_or_failures(yt):
    post = seed_youtube_video(yt, "vid_any")
    result = presence(yt, uploads_api([[]]))
    assert result["newly_deleted"] == 0 and result["unresolved"][0]["platform"] == "youtube"
    assert not deleted(yt, post)
    for kwargs in ({"fail_at": 1}, {"broken": "loop"}):
        result = presence(yt, uploads_api([["a"], ["b"]], **kwargs))
        assert result["newly_deleted"] == 0 and result["unresolved"]
        assert not deleted(yt, post)


def test_presence_skips_recent_videos_and_a_changed_channel(yt):
    recent = seed_youtube_video(yt, "vid_recent", minutes=1)
    result = presence(yt, uploads_api([["unrelated"]]))
    assert result["checked"] == 0 and not deleted(yt, recent)
    old = seed_youtube_video(yt, "vid_old")
    with yt.factory.begin() as session:
        session.execute(
            Account.__table__.update()
            .where(Account.platform == "youtube")
            .values(external_id="UC_other_channel")
        )
    result = presence(yt, uploads_api([["unrelated"]]))
    # 發佈當時的頻道已不是目前連結的頻道：無法判定，也不標記刪除。
    assert result["newly_deleted"] == 0 and not deleted(yt, old)


def test_hourly_sync_listing_reuses_the_complete_list_for_presence(yt):
    gone = seed_youtube_video(yt, "vid_gone")
    api = uploads_api([["vid_kept"]])
    workers = Workers(yt.factory, yt.settings, request=api)
    result = workers.metrics()
    assert result["errors"] == [] or all(e["platform"] != "youtube" for e in result["errors"])
    assert deleted(yt, gone)
    # 從分頁中途續跑的那一輪只有部分清單，不拿來判定。
    other = seed_youtube_video(yt, "vid_other")
    with yt.factory.begin() as session:
        row = session.scalar(
            select(Setting).where(Setting.key == "youtube.listing.UC_isolated_channel")
        )
        row.value_json = {"after": "1"}
    api = uploads_api([["unused"], ["vid_kept"]])
    Workers(yt.factory, yt.settings, request=api).metrics()
    assert not deleted(yt, other)


# ---- migration ----


@pytest.mark.migration
def test_youtube_migration_preserves_posts_and_refuses_lossy_downgrade(migrated):
    from app.db import build_engine, session_factory

    cfg = Config(str(REPO_ROOT / "backend/alembic.ini"))
    command.downgrade(cfg, "0042")
    engine = build_engine(migrated)
    columns = {c["name"] for c in inspect(engine).get_columns("publish_media")}
    assert "role" not in columns
    assert "role" not in {c["name"] for c in inspect(engine).get_columns("agent_uploads")}
    factory = session_factory(engine)
    with factory.begin() as session:
        brand = Brand(slug="yt-migration", name="隔離遷移")
        session.add(brand)
        session.flush()
        # 舊版 schema 沒有之後新增的 staff 欄位，只寫入當時就有的欄位。
        staff_id = session.execute(
            insert(Staff.__table__).values(
                username="yt-migration",
                display_name="隔離",
                role="admin",
                password_hash="isolated-hash",
            )
        ).inserted_primary_key[0]
        account = Account(
            brand_id=brand.id, platform="facebook", external_id="100", name="粉專", token_ref=""
        )
        post = PublishPost(
            brand_id=brand.id,
            creator_id=staff_id,
            format="video",
            caption="保留原文",
            platforms_json=["facebook"],
            platform_options_json={"facebook": {"video_format": "feed"}},
        )
        session.add_all([account, post])
        session.flush()
        # 舊 schema 沒有 role 欄位，ORM 無法寫入；以舊欄位直接插入既有素材。
        session.execute(
            text(
                "INSERT INTO publish_media (created_at, updated_at, post_id, position,"
                " original_name, relative_path, mime, size, width, height, duration, sha256,"
                " uploader_id) VALUES ('2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00',"
                " :post, 0, 'a.mp4', 'legacy-media', 'video/mp4', 10, 1, 1, 1.0, :sha, :staff)"
            ),
            {"post": post.id, "sha": "0" * 64, "staff": staff_id},
        )
        session.add(PublishTarget(post_id=post.id, platform="facebook", account_id=account.id))
        ids = (brand.id, staff_id, post.id, account.id)
    engine.dispose()
    command.upgrade(cfg, "head")
    engine = build_engine(migrated)
    factory = session_factory(engine)
    try:
        brand, staff, post, account = ids
        with factory.begin() as session:
            row = session.get(PublishPost, post)
            assert row.caption == "保留原文" and row.platforms_json == ["facebook"]
            media = session.scalar(select(PublishMedia))
            assert media.role == "media" and media.relative_path == "legacy-media"
            assert "role" in {c["name"] for c in inspect(engine).get_columns("agent_uploads")}
            session.add(PublishTarget(post_id=post, platform="youtube", account_id=account))
        with pytest.raises(RuntimeError, match="Existing YouTube"):
            command.downgrade(cfg, "0042")
        with factory.begin() as session:
            for item in session.scalars(
                select(PublishTarget).where(PublishTarget.platform == "youtube")
            ):
                session.delete(item)
            session.add(
                PublishMedia(
                    post_id=post,
                    position=0,
                    original_name="t.jpg",
                    relative_path="legacy-thumb",
                    mime="image/jpeg",
                    size=10,
                    width=1,
                    height=1,
                    sha256="1" * 64,
                    uploader_id=staff,
                    role="thumbnail",
                )
            )
        with pytest.raises(RuntimeError, match="Existing YouTube"):
            command.downgrade(cfg, "0042")
        with factory.begin() as session:
            for item in session.scalars(
                select(PublishMedia).where(PublishMedia.role == "thumbnail")
            ):
                session.delete(item)
        command.downgrade(cfg, "0042")
        engine.dispose()
        engine = build_engine(migrated)
        factory = session_factory(engine)
        assert "role" not in {c["name"] for c in inspect(engine).get_columns("publish_media")}
        with factory.begin() as session:
            with pytest.raises(IntegrityError):
                session.add(PublishTarget(post_id=post, platform="youtube", account_id=account))
                session.flush()
        command.upgrade(cfg, "head")
    finally:
        engine.dispose()

