"""Facebook「+ 評論」：發文成功後由粉專依序留言，失敗重試只接續剩下的評論（全部假 HTTP）。"""

import pytest
import test_publish
from publish_http_mock import jpeg_bytes, video_bytes
from sqlalchemy import select
from test_publish import action, create, targets_of, update_options

from app.models import OAuthConnection

# 共用發佈測試的隔離環境（假 HTTP、已連結平台）；以變數引用，參數同名不算重複匯入。
ready = test_publish.ready


def grant_engagement(ready):
    client = ready[0]
    with client.app.state.session_factory.begin() as session:
        row = session.scalar(select(OAuthConnection).where(OAuthConnection.platform == "meta"))
        granted = [*row.granted_scopes, "pages_manage_engagement"]
        row.granted_scopes = granted
        row.cache_json = {**row.cache_json, "granted": granted}


def comment_posts(mock):
    return [
        (path, fields.get("message"))
        for method, _, path, fields in mock.requests
        if method == "POST" and path.endswith("/comments")
    ]


@pytest.mark.parametrize("format", ["text", "image", "video"])
def test_comments_follow_the_post_in_order(ready, format):
    client, _, mock = ready
    grant_engagement(ready)
    comments = ["第一則 **重點**", "第二則"]
    post = create(ready, format, ["facebook"], options={"facebook": {"comments": comments}})
    assert post["platform_options"]["facebook"]["comments"] == comments
    assert action(client, post).status_code == 200
    target = targets_of(ready, post["id"])["facebook"]
    assert target.status == "succeeded"
    # 評論掛在剛發出的貼文上，依序送出，Markdown 已轉成平台文字。
    assert comment_posts(mock) == [
        ("/v26.0/" + target.platform_post_id + "/comments", "第一則 重點"),
        ("/v26.0/" + target.platform_post_id + "/comments", "第二則"),
    ]
    detail = target.detail_json
    assert detail["post_id"] == target.platform_post_id
    assert detail["successful_comments"] == detail["total_comments"] == 2
    assert detail["comment_ids"] == [identity for identity, _ in mock.comments]


def test_no_comments_keeps_the_single_request_path(ready):
    client, _, mock = ready
    post = create(ready, "text", ["facebook"])
    assert action(client, post).status_code == 200
    assert comment_posts(mock) == []
    assert "post_id" not in targets_of(ready, post["id"])["facebook"].detail_json


def test_missing_engagement_permission_blocks_before_sending(ready):
    client, _, mock = ready
    post = create(ready, "text", ["facebook"], options={"facebook": {"comments": ["一則"]}})
    check = client.post(f"/api/publish/posts/{post['id']}/check").json()["facebook"]
    assert not check["ok"] and any("pages_manage_engagement" in r for r in check["reasons"])
    result = action(client, post)
    assert result.status_code == 422 and "pages_manage_engagement" in result.json()["detail"]
    assert not mock.requests


def test_comment_rules_blank_count_and_facebook_draft(ready):
    client, _, _ = ready
    grant_engagement(ready)
    post = create(ready, "text", ["facebook"], options={"facebook": {"comments": ["一則", " "]}})
    check = client.post(f"/api/publish/posts/{post['id']}/check").json()["facebook"]
    assert not check["ok"] and "Facebook：評論 2 不可空白" in check["reasons"]
    many = create(ready, "text", ["facebook"], options={"facebook": {"comments": ["x"] * 21}})
    check = client.post(f"/api/publish/posts/{many['id']}/check").json()["facebook"]
    assert "Facebook：評論最多 20 則" in check["reasons"]
    draft = create(
        ready, "text", ["facebook"], unpublished=True, options={"facebook": {"comments": ["一則"]}}
    )
    check = client.post(f"/api/publish/posts/{draft['id']}/check").json()["facebook"]
    assert check["ok"] and "存成 FB 草稿時不會留評論" in check["warnings"]


def test_facebook_draft_never_comments(ready):
    client, _, mock = ready
    grant_engagement(ready)
    post = create(
        ready, "text", ["facebook"], unpublished=True, options={"facebook": {"comments": ["一則"]}}
    )
    assert action(client, post).status_code == 200
    assert comment_posts(mock) == []
    assert targets_of(ready, post["id"])["facebook"].status == "succeeded"


@pytest.mark.parametrize("fault", ["fail", "lost"])
def test_failed_comment_keeps_post_and_retry_only_continues(ready, fault):
    client, _, mock = ready
    grant_engagement(ready)
    comments = ["一", "二", "三"]
    (mock.fail_comments if fault == "fail" else mock.lost_comments).add("二")
    post = create(ready, "image", ["facebook"], options={"facebook": {"comments": comments}})
    assert action(client, post).status_code == 200
    row = targets_of(ready, post["id"])["facebook"]
    assert row.status == "failed" and row.detail_json["failed_comment"] == 2
    assert row.detail_json["successful_comments"] == 1
    first_id, posted = row.platform_post_id, row.detail_json["post_id"]
    current = client.get(f"/api/publish/posts/{post['id']}").json()
    # 貼文已發出：整篇算部分成功，評論不能再改。
    assert current["status"] == "partial"
    changed = update_options(ready, current, {"facebook": {"comments": ["改過"]}})
    assert changed.status_code == 409
    mock.requests.clear()
    assert action(client, current, "retry").status_code == 200
    # 重試不重發貼文；回應遺失的那則已在平台上，只補還沒留的評論。
    assert not any(path.endswith(("/feed", "/photos")) for _, _, path, _ in mock.requests)
    expected = ["三"] if fault == "lost" else ["二", "三"]
    assert [message for _, message in comment_posts(mock)] == expected
    assert [message for _, message in mock.comments] == comments
    row = targets_of(ready, post["id"])["facebook"]
    assert row.status == "succeeded" and row.platform_post_id == first_id == posted
    assert row.detail_json["successful_comments"] == 3 and row.detail_json["failed_comment"] is None


def upload_comment_image(ready, post, content, expected=200):
    response = ready[0].post(
        f"/api/publish/posts/{post['id']}/media?role=fb_comment&filename=c.jpg",
        content=content,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == expected, response.text
    return response.json()


def test_comment_images_are_sent_as_files_in_order(ready):
    client, _, mock = ready
    grant_engagement(ready)
    post = create(ready, "text", ["facebook"], options={"facebook": {"comments": ["一", "", "三"]}})
    post = upload_comment_image(ready, post, jpeg_bytes(800, 600))
    post = upload_comment_image(ready, post, jpeg_bytes(600, 800))
    first, second = (row["id"] for row in post["facebook_comment_media"])
    # 評論圖片不算貼文素材，純文字貼文也能附。
    assert post["media"] == [] and post["format"] == "text"
    saved = update_options(
        ready, post, {"facebook": {"comments": ["一", "", "三"], "comment_media": [second, first]}}
    )
    assert saved.status_code == 200, saved.text
    # 只有圖片、沒有文字的評論可以送出。
    assert saved.json()["platform_options"]["facebook"]["comment_media"] == [second, first, None]
    assert client.post(f"/api/publish/posts/{post['id']}/check").json()["facebook"]["ok"]
    assert action(client, saved.json()).status_code == 200
    target = targets_of(ready, post["id"])["facebook"]
    assert target.status == "succeeded"
    assert [message for _, message in comment_posts(mock)] == ["一", None, "三"]
    ids = [identity for identity, _ in mock.comments]
    assert set(mock.comment_files) == {ids[0], ids[1]}
    assert target.detail_json["comment_media"] == [second, first, None]


def test_comment_images_reject_video_foreign_and_duplicate_ids(ready):
    client, _, _ = ready
    grant_engagement(ready)
    post = create(ready, "text", ["facebook"], options={"facebook": {"comments": ["一", "二"]}})
    upload_comment_image(ready, post, video_bytes(), expected=422)
    post = upload_comment_image(ready, post, jpeg_bytes(800, 600))
    image = post["facebook_comment_media"][0]["id"]
    other = create(ready, "image", ["facebook"])
    for ids in ([image, image], [other["media"][0]["id"], None]):
        response = update_options(
            ready, post, {"facebook": {"comments": ["一", "二"], "comment_media": ids}}
        )
        assert response.status_code == 422 and "評論圖片" in response.json()["detail"]
    saved = update_options(
        ready, post, {"facebook": {"comments": ["一", " "], "comment_media": [None, image]}}
    ).json()
    assert client.post(f"/api/publish/posts/{post['id']}/check").json()["facebook"]["reasons"] == []
    # 移除圖片時同時清掉評論的引用：空白評論又會被擋下。
    removed = client.delete(f"/api/publish/posts/{post['id']}/media/{image}")
    assert removed.status_code == 200
    body = removed.json()
    assert body["facebook_comment_media"] == []
    assert body["platform_options"]["facebook"]["comment_media"] == [None, None]
    assert saved["version"] <= body["version"]
    check = client.post(f"/api/publish/posts/{post['id']}/check").json()["facebook"]
    assert "Facebook：評論 2 不可空白" in check["reasons"]
