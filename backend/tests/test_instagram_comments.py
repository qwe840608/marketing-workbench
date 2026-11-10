"""Instagram「+ 評論」：發文成功後由 IG 帳號依序留言（只有文字），重試只接續剩下的評論。"""

from types import SimpleNamespace

import pytest
import test_publish
from test_publish import action, create, targets_of, update_options

from app.services import publish_rules

# 共用發佈測試的隔離環境（假 HTTP、已連結平台）；以變數引用，參數同名不算重複匯入。
ready = test_publish.ready


def comment_posts(mock):
    return [
        (path, fields.get("message"))
        for method, _, path, fields in mock.requests
        if method == "POST" and path.endswith("/comments")
    ]


@pytest.mark.parametrize("format", ["image", "carousel", "video"])
def test_comments_follow_the_ig_post_in_order(ready, format):
    client, _, mock = ready
    comments = ["第一則 **重點**", "第二則"]
    post = create(ready, format, ["instagram"], options={"instagram": {"comments": comments}})
    assert post["platform_options"]["instagram"]["comments"] == comments
    assert action(client, post).status_code == 200
    target = targets_of(ready, post["id"])["instagram"]
    assert target.status == "succeeded"
    # 評論掛在剛發佈的 IG 媒體上，依序送出，Markdown 已轉成平台文字，沒有附圖。
    assert comment_posts(mock) == [
        ("/v26.0/" + target.platform_post_id + "/comments", "第一則 重點"),
        ("/v26.0/" + target.platform_post_id + "/comments", "第二則"),
    ]
    assert not mock.comment_files
    detail = target.detail_json
    assert detail["post_id"] == target.platform_post_id
    assert detail["successful_comments"] == detail["total_comments"] == 2


def test_no_ig_comments_keeps_the_single_request_path(ready):
    client, _, mock = ready
    post = create(ready, "image", ["instagram"])
    assert action(client, post).status_code == 200
    assert comment_posts(mock) == []
    assert "post_id" not in targets_of(ready, post["id"])["instagram"].detail_json


def test_ig_comment_rules_blank_count_and_length(ready):
    client, _, _ = ready
    post = create(ready, "image", ["instagram"], options={"instagram": {"comments": ["一則", " "]}})
    check = client.post(f"/api/publish/posts/{post['id']}/check").json()["instagram"]
    assert not check["ok"] and "Instagram：評論 2 不可空白" in check["reasons"]
    many = create(ready, "image", ["instagram"], options={"instagram": {"comments": ["x"] * 21}})
    check = client.post(f"/api/publish/posts/{many['id']}/check").json()["instagram"]
    assert "Instagram：評論最多 20 則" in check["reasons"]
    long = create(ready, "image", ["instagram"], options={"instagram": {"comments": ["字" * 2201]}})
    check = client.post(f"/api/publish/posts/{long['id']}/check").json()["instagram"]
    assert not check["ok"] and any("評論 1" in reason for reason in check["reasons"])
    # FB 草稿只影響 Facebook：IG 評論照常送出，不出現 FB 草稿提示。
    result = publish_rules.check(
        "instagram", "text", "x", [], {"comments": ["一則"]}, unpublished=True
    )
    assert "存成 FB 草稿時不會留評論" not in result["warnings"]


def test_ig_story_never_comments():
    post = SimpleNamespace(
        format="story", facebook_unpublished=False,
        platform_options_json={"instagram": {"comments": ["一則"]}},
    )
    assert publish_rules.instagram_comments(post) == []
    post.format = "image"
    assert publish_rules.instagram_comments(post) == ["一則"]


@pytest.mark.parametrize("fault", ["fail", "lost"])
def test_failed_ig_comment_keeps_post_and_retry_only_continues(ready, fault):
    client, _, mock = ready
    comments = ["一", "二", "三"]
    (mock.fail_comments if fault == "fail" else mock.lost_comments).add("二")
    post = create(ready, "image", ["instagram"], options={"instagram": {"comments": comments}})
    assert action(client, post).status_code == 200
    row = targets_of(ready, post["id"])["instagram"]
    assert row.status == "failed" and row.detail_json["failed_comment"] == 2
    first_id = row.platform_post_id
    current = client.get(f"/api/publish/posts/{post['id']}").json()
    assert current["status"] == "partial"
    changed = update_options(ready, current, {"instagram": {"comments": ["改過"]}})
    assert changed.status_code == 409
    mock.requests.clear()
    assert action(client, current, "retry").status_code == 200
    # 重試不重發 IG 媒體；回應遺失的那則已在平台上，只補還沒留的評論。
    assert not any(path.endswith(("/media", "/media_publish")) for _, _, path, _ in mock.requests)
    expected = ["三"] if fault == "lost" else ["二", "三"]
    assert [message for _, message in comment_posts(mock)] == expected
    assert [message for _, message in mock.comments] == comments
    row = targets_of(ready, post["id"])["instagram"]
    assert row.status == "succeeded" and row.platform_post_id == first_id
    assert row.detail_json["successful_comments"] == 3 and row.detail_json["failed_comment"] is None
