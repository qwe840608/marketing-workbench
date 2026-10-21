"""Facebook video/Reels cover: upload, apply after success, failure, reapply (all mocked HTTP)."""

import test_publish
from publish_http_mock import jpeg_bytes, video_bytes
from sqlalchemy import select
from test_publish import action, create

from app.models import AuditLog, OAuthConnection, PublishTarget
from app.services import oauth, publish_rules

# 共用發佈測試的隔離環境（假 HTTP、已連結平台）；以變數引用，參數同名不算重複匯入。
ready = test_publish.ready


def upload_cover(ready, post, content, expected=200, filename="fb.jpg"):
    response = ready[0].post(
        f"/api/publish/posts/{post['id']}/media?role=fb_cover&filename={filename}",
        content=content,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == expected, response.text
    return response.json()


def facebook_target(ready, post):
    body = ready[0].get(f"/api/publish/posts/{post['id']}").json()
    return next(t for t in body["targets"] if t["platform"] == "facebook")


def reels_post(ready, video_format="reels"):
    return create(
        ready, "video", ["facebook"], options={"facebook": {"video_format": video_format}}
    )


def test_facebook_cover_is_bound_and_separate_from_instagram(ready):
    client = ready[0]
    post = reels_post(ready)
    post = upload_cover(ready, post, jpeg_bytes(1080, 1920))
    cover = post["facebook_cover"]
    assert cover["name"] == "fb.jpg" and post["cover"] is None and post["thumbnail"] is None
    assert post["platform_options"]["facebook"]["cover_media_id"] == cover["id"]
    assert [m["mime"] for m in post["media"]] == ["video/mp4"]
    replaced = upload_cover(ready, post, jpeg_bytes(1080, 1920), filename="new.jpg")
    assert replaced["facebook_cover"]["id"] != cover["id"]
    removed = client.delete(
        f"/api/publish/posts/{post['id']}/media/{replaced['facebook_cover']['id']}"
    )
    assert removed.status_code == 200 and removed.json()["facebook_cover"] is None
    assert removed.json()["platform_options"]["facebook"]["cover_media_id"] is None
    upload_cover(ready, create(ready, "image", ["facebook"]), jpeg_bytes(), expected=422)
    upload_cover(ready, post, video_bytes(), expected=422)


def test_facebook_cover_ratio_hint(ready):
    post = upload_cover(ready, reels_post(ready), jpeg_bytes(1080, 1080))
    result = ready[0].post(f"/api/publish/posts/{post['id']}/check").json()["facebook"]
    assert result["ok"] and publish_rules.FB_COVER_RATIO_WARNING in result["warnings"]
    post = upload_cover(ready, post, jpeg_bytes(1080, 1920))
    result = ready[0].post(f"/api/publish/posts/{post['id']}/check").json()["facebook"]
    assert publish_rules.FB_COVER_RATIO_WARNING not in result["warnings"]


def test_cover_is_applied_after_the_reel_or_video_succeeds(ready):
    client, _, mock = ready
    for video_format in ("reels", "feed"):
        mock.covers.clear()
        post = upload_cover(ready, reels_post(ready, video_format), jpeg_bytes(1080, 1920))
        assert action(client, post).status_code == 200
        target = facebook_target(ready, post)
        assert target["status"] == "succeeded"
        assert target["detail"]["cover"] == {"status": "applied"}
        ((path, fields, content),) = mock.covers
        # 封面套用在本次建立的影片上，且設為偏好封面；影片不會重傳。
        assert path == "/v26.0/" + target["platform_post_id"] + "/thumbnails"
        assert fields.get("is_preferred") == "true" and b'name="source"' in content


def test_no_cover_means_no_thumbnail_call(ready):
    client, _, mock = ready
    post = reels_post(ready)
    assert action(client, post).status_code == 200
    assert mock.covers == [] and "cover" not in facebook_target(ready, post)["detail"]


def test_cover_failure_keeps_post_and_can_be_reapplied(ready):
    client, _, mock = ready
    post = upload_cover(ready, reels_post(ready), jpeg_bytes(1080, 1920))
    mock.fail_cover = 200
    assert action(client, post).status_code == 200
    target = facebook_target(ready, post)
    # 封面失敗不影響貼文成功，原因是中文說明。
    assert target["status"] == "succeeded" and target["permalink"]
    assert target["detail"]["cover"]["status"] == "failed"
    assert target["detail"]["cover"]["code"] == "permission_missing"
    errors = publish_rules.FB_COVER_ERRORS
    assert target["detail"]["cover"]["reason"] == errors["permission_missing"]
    uploads = len(mock.uploads)
    mock.fail_cover = None
    response = client.post(
        f"/api/publish/posts/{post['id']}/facebook-cover", json={"confirmed": True}
    )
    assert response.status_code == 200, response.text
    target = next(t for t in response.json()["targets"] if t["platform"] == "facebook")
    assert target["detail"]["cover"] == {"status": "applied"}
    assert len(mock.uploads) == uploads  # 只套用封面，不重傳影片
    again = client.post(f"/api/publish/posts/{post['id']}/facebook-cover", json={"confirmed": True})
    assert again.status_code == 409
    with client.app.state.session_factory() as session:
        actions = session.scalars(
            select(AuditLog.action).where(AuditLog.action == "publish.facebook.cover")
        ).all()
        assert actions == ["publish.facebook.cover"]
        assert session.scalar(select(PublishTarget).where(PublishTarget.platform == "facebook"))


def test_cover_hint_only_when_engagement_permission_is_missing(ready):
    client, brand, _ = ready
    options = client.get(f"/api/publish/options?brand_id={brand}").json()["platforms"]
    # 缺少選用權限不影響發佈就緒，只提示自訂封面需要重新連結。
    assert options["facebook"]["ready"] is True
    assert options["facebook"]["cover_hint"] == oauth.FACEBOOK_COVER_HINT
    assert "cover_hint" not in options["instagram"]
    with client.app.state.session_factory.begin() as session:
        row = session.scalar(select(OAuthConnection).where(OAuthConnection.platform == "meta"))
        granted = [*row.granted_scopes, "pages_manage_engagement"]
        row.granted_scopes = granted
        row.cache_json = {**row.cache_json, "granted": granted}
    options = client.get(f"/api/publish/options?brand_id={brand}").json()["platforms"]
    assert options["facebook"]["ready"] is True and "cover_hint" not in options["facebook"]
    assert "pages_manage_engagement" in oauth.SCOPES["meta"]
    assert "pages_manage_engagement" not in oauth.META_SCOPES
