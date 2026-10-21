"""TikTok 發佈（送到收件匣）：所有 TikTok 請求都走 MockTransport，素材為合成影片。

只送影片、收件匣 API 不帶文案、publish_id 先保存避免重送、收件匣額滿的錯誤、
之後追蹤使用者是否在 App 內發佈、LINE 通知提醒到 App 完成。
"""

from types import SimpleNamespace

import httpx
import pytest
from publish_http_mock import jpeg_bytes, seed_tiktok, video_bytes
from sqlalchemy import select
from test_youtube_publish import build, fresh, make, submit, target

from app.models import NotificationDelivery
from app.models.base import utc_now
from app.services import notify, publish, publish_rules, publish_tiktok

CAPTION = "隔離 TikTok 文案 #標籤"


@pytest.fixture
def tt(client, settings, monkeypatch):
    env = build(client, settings, monkeypatch)
    monkeypatch.setattr(publish_tiktok, "POLL_SECONDS", 0)
    monkeypatch.setattr(publish_tiktok.time, "sleep", lambda seconds: None)
    with env.factory.begin() as session:
        seed_tiktok(session, settings, env.brand)
    env.tiktok = env.mock.tiktok
    return env


def tiktok_post(tt, **kwargs):
    return make(tt, platforms=("tiktok",), caption=CAPTION, video=video_bytes(1080, 1920), **kwargs)


def test_options_and_rules_only_allow_video(tt):
    options = tt.client.get(f"/api/publish/options?brand_id={tt.brand}").json()
    assert options["platforms"]["tiktok"]["ready"] is True
    assert options["rules"]["tiktok"]["video_seconds"] == 600
    image = make(tt, format="image", platforms=("tiktok",), caption=CAPTION)
    result = tt.client.post(f"/api/publish/posts/{image['id']}/check").json()["tiktok"]
    assert not result["ok"]
    assert result["reasons"] == ["TikTok：僅支援影片發布，圖文需從APP上傳"]
    video = tiktok_post(tt)
    result = tt.client.post(f"/api/publish/posts/{video['id']}/check").json()["tiktok"]
    assert result["ok"], result
    assert publish_rules.TIKTOK_INBOX_NOTICE in result["warnings"]


def test_publish_sends_video_to_inbox_without_caption(tt, monkeypatch):
    monkeypatch.setattr(
        notify,
        "load_policy",
        lambda session, brand_id: (
            SimpleNamespace(enabled=True, group_id="C" + "1" * 32),
            None,
            None,
        ),
    )
    post = tiktok_post(tt)
    response = submit(tt, post)
    assert response.status_code == 200, response.text
    row = target(tt, post, "tiktok")
    assert row.status == "succeeded", (row.status, row.error_code)
    assert row.detail_json["inbox_state"] == "SEND_TO_USER_INBOX"
    assert row.detail_json["publish_id"] == "v_inbox_file~v2.1"
    (init,) = tt.tiktok.inits
    size = init["source_info"]["video_size"]
    assert init == {
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": size,
            "total_chunk_count": 1,
        }
    }
    assert tt.tiktok.chunks == [(0, size - 1, size)]
    # 收件匣 API 沒有文案欄位：文案絕不送出。
    sent = [c for c in tt.mock.calls if "tiktokapis" in c[1]]
    assert sent and all(CAPTION not in str(call) for call in sent)
    assert fresh(tt, post)["status"] == "done"
    with tt.factory() as session:
        text = session.scalars(select(NotificationDelivery)).all()[-1].messages_json[0]["text"]
    assert "已送到收件匣，請在 App 內完成發佈" in text


def test_large_file_is_split_into_ordered_chunks(tt, monkeypatch):
    monkeypatch.setattr(publish_tiktok, "SINGLE", 1000)
    monkeypatch.setattr(publish_tiktok, "CHUNK", 1000)
    post = make(
        tt, platforms=("tiktok",), caption=CAPTION, video=video_bytes(1080, 1920, padding=5500)
    )
    submit(tt, post)
    size = tt.tiktok.inits[0]["source_info"]["video_size"]
    chunks = tt.tiktok.chunks
    assert tt.tiktok.inits[0]["source_info"]["total_chunk_count"] == len(chunks) == size // 1000
    assert chunks[0][0] == 0 and chunks[-1][1] == size - 1
    assert all(a[1] + 1 == b[0] for a, b in zip(chunks, chunks[1:], strict=False))


def test_full_inbox_fails_with_reason_and_retry_does_not_resend(tt):
    tt.tiktok.inbox_full = True
    post = tiktok_post(tt)
    submit(tt, post)
    row = target(tt, post, "tiktok")
    assert (row.status, row.error_code) == ("failed", "inbox_full")
    reason = next(t for t in fresh(tt, post)["targets"] if t["platform"] == "tiktok")["reason"]
    assert reason == publish_rules.ERRORS["inbox_full"]
    # 先前已建立 publish_id 且已進收件匣：重試只查狀態，不再送一次。
    tt.tiktok.inbox_full = False
    with tt.factory.begin() as session:
        target_row = session.get(type(row), row.id)
        target_row.detail_json = {
            "publish_id": "v_inbox_file~v2.9",
            "inbox_state": "PROCESSING_UPLOAD",
        }
    tt.tiktok.states = ["SEND_TO_USER_INBOX"]
    retry = submit(tt, fresh(tt, post), endpoint="retry")
    assert retry.status_code == 200, retry.text
    row = target(tt, post, "tiktok")
    assert row.status == "succeeded" and len(tt.tiktok.inits) == 1


def test_refresh_records_when_the_creator_posts_from_the_app(tt):
    post = tiktok_post(tt)
    submit(tt, post)
    tt.tiktok.states = ["PUBLISH_COMPLETE"]
    tt.tiktok.statuses.clear()
    tt.tiktok.posted_ids = [7400000000000000001]
    # 剛查過不到 10 分鐘：不查。
    assert publish_tiktok.refresh(tt.factory, tt.settings) == 0
    later = utc_now() + publish_tiktok.REFRESH_GAP * 2
    assert publish.tick(tt.factory, tt.settings, later)["tiktok_checked"] == 1
    row = target(tt, post, "tiktok")
    assert row.detail_json["inbox_state"] == "PUBLISH_COMPLETE"
    assert row.platform_post_id == "7400000000000000001"
    # 已完成就不再追蹤。
    assert (
        publish_tiktok.refresh(tt.factory, tt.settings, later + publish_tiktok.REFRESH_GAP * 2) == 0
    )


def test_plan_follows_the_media_transfer_guide():
    mb = publish_tiktok.MB
    assert publish_tiktok.plan(3 * mb) == (3 * mb, 1)
    assert publish_tiktok.plan(64 * mb) == (64 * mb, 1)
    chunk, count = publish_tiktok.plan(1024 * mb)
    assert chunk == 10 * mb and count == 102
    assert 1024 * mb - chunk * (count - 1) <= 128 * mb
    assert jpeg_bytes()


def retry_with(tt, post, row, detail, states):
    with tt.factory.begin() as session:
        target_row = session.get(type(row), row.id)
        target_row.detail_json = detail
    tt.tiktok.states = states
    response = submit(tt, fresh(tt, post), endpoint="retry")
    assert response.status_code == 200, response.text
    return target(tt, post, "tiktok")


def test_retry_follows_a_finished_upload_instead_of_uploading_again(tt):
    tt.tiktok.inbox_full = True
    post = tiktok_post(tt)
    submit(tt, post)
    row = target(tt, post, "tiktok")
    tt.tiktok.inbox_full = False
    # 上一次已全部上傳、TikTok 還在轉檔：重試只追蹤，不再送一次（收件匣 24 小時只能 5 支）。
    detail = {"publish_id": "v_inbox_file~v2.9", "inbox_state": "PROCESSING_UPLOAD"}
    row = retry_with(
        tt, post, row, {**detail, "uploaded": True}, ["PROCESSING_UPLOAD", "SEND_TO_USER_INBOX"]
    )
    assert row.status == "succeeded" and len(tt.tiktok.inits) == 1
    assert row.detail_json["publish_id"] == "v_inbox_file~v2.9"


def test_retry_uploads_again_when_the_previous_upload_is_gone_or_unfinished(tt):
    tt.tiktok.inbox_full = True
    post = tiktok_post(tt)
    submit(tt, post)
    row = target(tt, post, "tiktok")
    tt.tiktok.inbox_full = False
    tt.tiktok.unknown_ids = {"v_inbox_file~v2.9"}
    row = retry_with(
        tt,
        post,
        row,
        {"publish_id": "v_inbox_file~v2.9", "inbox_state": "PROCESSING_UPLOAD", "uploaded": True},
        ["SEND_TO_USER_INBOX"],
    )
    assert row.status == "succeeded" and len(tt.tiktok.inits) == 2


@pytest.mark.parametrize(
    ("reason", "code", "uploads"),
    [
        ("internal", None, 2),
        ("duration_check_failed", "media_rejected", 1),
        ("spam_risk", "spam_risk", 1),
        ("auth_removed", "token_invalid", 1),
    ],
)
def test_retry_after_failed_follows_the_official_retry_rules(tt, reason, code, uploads):
    tt.tiktok.inbox_full = True
    post = tiktok_post(tt)
    submit(tt, post)
    row = target(tt, post, "tiktok")
    tt.tiktok.inbox_full = False
    tt.tiktok.fail_reason = reason
    tt.tiktok.statuses.clear()
    row = retry_with(
        tt,
        post,
        row,
        {"publish_id": "v_inbox_file~v2.9", "inbox_state": "FAILED", "uploaded": True},
        ["FAILED", "SEND_TO_USER_INBOX"],
    )
    assert len(tt.tiktok.inits) == uploads
    assert (row.status, row.error_code) == (
        ("succeeded", None) if code is None else ("failed", code)
    )


def test_failed_after_reaching_processing_turns_the_target_failed(tt, monkeypatch):
    monkeypatch.setattr(
        notify,
        "load_policy",
        lambda session, brand_id: (
            SimpleNamespace(enabled=True, group_id="C" + "1" * 32),
            None,
            None,
        ),
    )
    monkeypatch.setattr(publish_tiktok, "SETTLE_SECONDS", 0)
    tt.tiktok.states = ["PROCESSING_UPLOAD"]
    post = tiktok_post(tt)
    submit(tt, post)
    assert target(tt, post, "tiktok").status == "succeeded"
    assert fresh(tt, post)["status"] == "done"
    # 之後 TikTok 回報影片長度不符：改為失敗、可重試，並再發一次通知。
    tt.tiktok.states = ["FAILED"]
    tt.tiktok.fail_reason = "duration_check_failed"
    later = utc_now() + publish_tiktok.REFRESH_GAP * 2
    assert publish.tick(tt.factory, tt.settings, later)["tiktok_checked"] == 1
    row = target(tt, post, "tiktok")
    assert (row.status, row.error_code) == ("failed", "media_rejected")
    assert row.detail_json["fail_reason"] == "duration_check_failed"
    assert fresh(tt, post)["status"] == "failed"
    with tt.factory() as session:
        text = session.scalars(select(NotificationDelivery)).all()[-1].messages_json[0]["text"]
    assert "tiktok：失敗" in text


def test_retry_does_not_upload_again_when_the_status_is_unreachable(tt):
    tt.tiktok.inbox_full = True
    post = tiktok_post(tt)
    submit(tt, post)
    row = target(tt, post, "tiktok")
    tt.tiktok.inbox_full = False
    handle = tt.tiktok.handle

    def unavailable(request):
        if request.url.path == "/v2/post/publish/status/fetch/":
            return httpx.Response(503, json={})
        return handle(request)

    tt.tiktok.handle = unavailable
    row = retry_with(
        tt,
        post,
        row,
        {"publish_id": "v_inbox_file~v2.9", "inbox_state": "PROCESSING_UPLOAD", "uploaded": True},
        ["SEND_TO_USER_INBOX"],
    )
    assert (row.status, row.error_code) == ("failed", "unknown")
    assert len(tt.tiktok.inits) == 1


def test_failed_inbox_does_not_override_a_scheduled_retry(tt, monkeypatch):
    from datetime import timedelta

    from app.models import PublishPost

    monkeypatch.setattr(publish_tiktok, "SETTLE_SECONDS", 0)
    tt.tiktok.states = ["PROCESSING_UPLOAD"]
    post = tiktok_post(tt)
    submit(tt, post)
    when = utc_now() + timedelta(hours=1)
    with tt.factory.begin() as session:
        # 例如其他平台失敗後已排程重試：這篇貼文正等待排程。
        row = session.get(PublishPost, post["id"])
        row.status, row.scheduled_at = "scheduled", when
    tt.tiktok.states = ["FAILED"]
    tt.tiktok.fail_reason = "duration_check_failed"
    later = utc_now() + publish_tiktok.REFRESH_GAP * 2
    assert publish_tiktok.refresh(tt.factory, tt.settings, later, failed=publish.finish) == 1
    row = target(tt, post, "tiktok")
    assert (row.status, row.error_code) == ("failed", "media_rejected")
    result = fresh(tt, post)
    assert result["status"] == "scheduled" and result["scheduled_at"] is not None
