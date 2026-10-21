"""Instagram Reels cover: upload, replace, remove, rule hints and the cover_url request (mocked)."""

import test_publish
from publish_http_mock import jpeg_bytes, video_bytes
from sqlalchemy import select
from test_publish import action, create, png_bytes

from app.models import PublishLink, PublishMedia, PublishPost
from app.services import publish, publish_media, publish_rules

# 共用發佈測試的隔離環境（假 HTTP、已連結平台）；以變數引用，參數同名不算重複匯入。
ready = test_publish.ready


def upload_cover(ready, post, content, expected=200, filename="cover.jpg"):
    client = ready[0]
    response = client.post(
        f"/api/publish/posts/{post['id']}/media?role=cover&filename={filename}",
        content=content,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == expected, response.text
    return response.json()


def checks(ready, post):
    response = ready[0].post(f"/api/publish/posts/{post['id']}/check")
    assert response.status_code == 200, response.text
    return response.json()


def reels_containers(mock):
    return [
        fields
        for method, _, path, fields in mock.requests
        if method == "POST" and path.endswith("/media") and fields.get("media_type") == "REELS"
    ]


def test_cover_is_bound_to_instagram_and_can_be_replaced_and_removed(ready):
    client = ready[0]
    post = create(ready, "video", ["instagram", "facebook"])
    post = upload_cover(ready, post, jpeg_bytes(1080, 1920))
    cover = post["cover"]
    assert cover["mime"] == "image/jpeg" and cover["name"] == "cover.jpg"
    assert post["platform_options"]["instagram"]["cover_media_id"] == cover["id"]
    # 封面不是發佈素材：影片仍只有一個媒體檔，其他平台看不到它，也不影響 YouTube 縮圖。
    assert [m["mime"] for m in post["media"]] == ["video/mp4"] and post["thumbnail"] is None
    factory, settings = client.app.state.session_factory, client.app.state.settings
    with factory() as session:
        assert [m.id for m in publish.media_rows(session, post["id"])] == [post["media"][0]["id"]]
        old_path = publish_media.path_for(settings, session.get(PublishMedia, cover["id"]))
    preview = client.get(f"/api/publish/posts/{post['id']}/media/{cover['id']}")
    assert preview.status_code == 200 and preview.headers["content-type"] == "image/jpeg"
    # 儲存草稿（含 IG 選項）不會清掉伺服端維護的封面編號。
    saved = client.put(
        f"/api/publish/posts/{post['id']}",
        json={
            "brand_id": post["brand_id"],
            "format": "video",
            "caption": post["caption"],
            "platforms": post["platforms"],
            "platform_options": {"instagram": {"share_to_feed": False}},
            "media_ids": [post["media"][0]["id"]],
            "version": post["version"],
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["platform_options"]["instagram"] == {
        "share_to_feed": False,
        "cover_media_id": cover["id"],
    }
    replaced = upload_cover(ready, saved.json(), png_bytes((1080, 1920)), filename="new.png")
    assert replaced["cover"]["id"] != cover["id"] and replaced["cover"]["mime"] == "image/png"
    assert not old_path.exists()
    removed = client.delete(f"/api/publish/posts/{post['id']}/media/{replaced['cover']['id']}")
    assert removed.status_code == 200
    assert removed.json()["cover"] is None
    assert removed.json()["platform_options"]["instagram"]["cover_media_id"] is None


def test_cover_upload_limits(ready):
    post = create(ready, "video", ["instagram"])
    upload_cover(ready, post, video_bytes(), expected=422)
    limit = publish_rules.RULES["instagram"]["cover_bytes"]
    assert limit == 8 * 1024**2
    upload_cover(ready, post, jpeg_bytes(1080, 1920) + b"0" * limit, expected=413)
    image = create(ready, "image", ["instagram"])
    upload_cover(ready, image, jpeg_bytes(1080, 1920), expected=422)


def test_cover_rule_hints_ratio_and_png(ready):
    post = create(ready, "video", ["instagram"])
    post = upload_cover(ready, post, jpeg_bytes(1080, 1920))
    assert checks(ready, post)["instagram"]["warnings"] == []
    post = upload_cover(ready, post, jpeg_bytes(1080, 1080))
    result = checks(ready, post)["instagram"]
    assert result["ok"] and result["warnings"] == [publish_rules.IG_COVER_RATIO_WARNING]
    post = upload_cover(ready, post, png_bytes((1080, 1920)), filename="c.png")
    result = checks(ready, post)["instagram"]
    assert result["ok"] and result["warnings"] == [publish_rules.IG_COVER_PNG_WARNING]


def test_reels_container_sends_cover_url_and_revokes_its_link(ready):
    client, _, mock = ready
    post = create(ready, "video", ["instagram", "facebook"])
    post = upload_cover(ready, post, png_bytes((1080, 1920)), filename="c.png")
    mock.requests.clear()
    assert action(client, post).status_code == 200
    assert client.get(f"/api/publish/posts/{post['id']}").json()["status"] == "done"
    (container,) = reels_containers(mock)
    # PNG 封面以 .jpg 連結送出（cover_url 只收 JPEG），與影片連結不同。
    assert container["cover_url"].endswith(".jpg")
    assert container["cover_url"] != container["video_url"]
    assert "thumb_offset" not in container
    # Facebook 不送封面：請求裡沒有任何封面欄位。
    assert not any(
        "cover_url" in fields
        for _, host, _, fields in mock.requests
        if host == "graph.facebook.com" and fields.get("media_type") != "REELS"
    )
    with client.app.state.session_factory() as session:
        links = list(session.scalars(select(PublishLink)))
        assert len(links) == 2 and all(link.revoked_at for link in links)


def test_reels_without_cover_request_is_unchanged(ready):
    client, _, mock = ready
    post = create(ready, "video", ["instagram"])
    assert action(client, post).status_code == 200
    (container,) = reels_containers(mock)
    assert "cover_url" not in container


def test_cover_cannot_change_after_instagram_was_sent(ready):
    client = ready[0]
    post = create(ready, "video", ["instagram"])
    post = upload_cover(ready, post, jpeg_bytes(1080, 1920))
    assert action(client, post).status_code == 200
    # 模擬部分成功後取消排程回到草稿：IG 目標仍是成功，封面不能再換或移除。
    with client.app.state.session_factory.begin() as session:
        session.get(PublishPost, post["id"]).status = "draft"
    current = client.get(f"/api/publish/posts/{post['id']}").json()
    upload_cover(ready, current, jpeg_bytes(1080, 1920), expected=409)
    removed = client.delete(f"/api/publish/posts/{post['id']}/media/{current['cover']['id']}")
    assert removed.status_code == 409
