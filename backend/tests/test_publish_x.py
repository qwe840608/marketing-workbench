"""X 發佈：所有平台請求都走 MockTransport，素材為合成檔案。

規則（加權字數與網址費用）、媒體上傳、建立貼文、回應中斷時讀回確認不重複發文、
明確拒絕的錯誤原因。
"""

import pytest
from publish_http_mock import jpeg_bytes, seed_x, video_bytes
from test_youtube_publish import build, fresh, make, submit, target

from app.services import publish_rules, publish_x

X_CAPTION = "隔離 X 文案 & 測試 #標籤"


@pytest.fixture
def env(client, settings, monkeypatch):
    env = build(client, settings, monkeypatch)
    monkeypatch.setattr(publish_x.time, "sleep", lambda seconds: None)
    with env.factory.begin() as session:
        seed_x(session, settings, env.brand)
    env.x = env.mock.x
    return env


def check(env, post, platform):
    response = env.client.post(f"/api/publish/posts/{post['id']}/check")
    assert response.status_code == 200, response.text
    return response.json()[platform]


def test_x_weighted_length_and_url_cost_warning():
    assert publish_rules.x_weight("a" * 280) == 280
    assert publish_rules.x_weight("中" * 140) == 280
    assert (
        publish_rules.x_weight("看 https://example.com/" + "a" * 80 + " 好") == 2 + 1 + 23 + 1 + 2
    )
    assert publish_rules.x_weight("👍🏽") == 2
    result = publish_rules.check("x", "text", "中" * 141, [])
    assert result["reasons"] == ["X：" + publish_rules.X_CAPTION_LABEL + "超過 280 字上限"]
    assert publish_rules.overflow("中" * 141, 280, "x") == (141, "中")
    result = publish_rules.check("x", "text", "看這裡 https://example.com", [])
    assert result["ok"] and any("$0.20" in w for w in result["warnings"])
    assert publish_rules.check("x", "story", "", [])["supported"] is False


def test_options_include_x(env):
    options = env.client.get(f"/api/publish/options?brand_id={env.brand}").json()
    assert options["platforms"]["x"]["ready"] is True
    assert options["rules"]["x"]["caption"] == 280


def test_x_text_post_is_created_once(env):
    post = make(env, format="text", platforms=("x",), caption=X_CAPTION)
    assert check(env, post, "x")["ok"]
    response = submit(env, post)
    assert response.status_code == 200, response.text
    row = target(env, post, "x")
    assert row.status == "succeeded", (row.status, row.error_code)
    assert env.x.posts == [{"text": X_CAPTION}]
    assert row.permalink == "https://x.com/i/web/status/" + row.platform_post_id
    assert fresh(env, post)["status"] == "done"


def test_x_images_are_uploaded_and_attached(env):
    post = make(env, format="carousel", platforms=("x",), caption=X_CAPTION, video=jpeg_bytes())
    submit(env, post)
    row = target(env, post, "x")
    assert row.status == "succeeded", row.error_code
    assert [i["media_category"] for i in env.x.inits] == ["tweet_image", "tweet_image"]
    assert env.x.posts[0]["media"] == {"media_ids": ["7001", "7002"]}


def test_x_video_waits_for_processing(env):
    env.x.processing = ["in_progress", "succeeded"]
    post = make(env, platforms=("x",), caption=X_CAPTION, video=video_bytes(1280, 720))
    assert check(env, post, "x")["ok"]
    submit(env, post)
    row = target(env, post, "x")
    assert row.status == "succeeded", row.error_code
    assert env.x.inits[0]["media_category"] == "tweet_video"
    assert env.x.processing == []


def test_x_lost_response_is_confirmed_by_reading_back_not_reposting(env):
    env.x.lose_post = True
    post = make(env, format="text", platforms=("x",), caption=X_CAPTION)
    submit(env, post)
    row = target(env, post, "x")
    assert (row.status, row.error_code) == ("failed", "timeout")
    assert row.detail_json.get("creating_at")
    env.x.lose_post = False
    retry = submit(env, fresh(env, post), endpoint="retry")
    assert retry.status_code == 200, retry.text
    row = target(env, post, "x")
    assert row.status == "succeeded", row.error_code
    # 讀回自己的最新貼文找到同一則：只送過一次。
    assert len(env.x.posts) == 1 and len(env.x.timeline_reads) == 1
    assert row.platform_post_id == env.x.timeline[0]["id"]


@pytest.mark.parametrize(
    ("status", "body", "code"),
    [
        (402, {"title": "CreditsDepleted"}, "credits_exhausted"),
        (
            403,
            {"detail": "You are not allowed to create a Tweet with duplicate content."},
            "duplicate_content",
        ),
        (401, {"title": "Unauthorized"}, "token_invalid"),
        (429, {"title": "Too Many Requests"}, "rate_limited"),
    ],
)
def test_x_rejections_have_reasons_and_clear_the_pending_mark(env, status, body, code):
    env.x.post_error = (status, body)
    post = make(env, format="text", platforms=("x",), caption=X_CAPTION)
    submit(env, post)
    row = target(env, post, "x")
    assert (row.status, row.error_code) == ("failed", code)
    assert "creating_at" not in row.detail_json
    reason = next(t for t in fresh(env, post)["targets"] if t["platform"] == "x")["reason"]
    assert reason == publish_rules.ERRORS[code]
