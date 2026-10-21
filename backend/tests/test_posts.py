import copy
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from conftest import call_service, deliver_event
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select

from app.models import Account, Brand, MetricSnapshot, Post, Setting, Staff, StaffBrand, Thread
from app.schemas.posts import MetricsInput, PostsInput
from app.services import posts as posts_service
from app.services.access import BrandAccess
from app.services.posts import (
    due_metrics,
    effective_tier,
    list_posts,
    schedule_tier,
    set_schedule_override,
)


@pytest.fixture
def post_data(client, settings):
    settings.ingest_api_key = SecretStr(secrets.token_urlsafe(32))
    with client.app.state.session_factory.begin() as session:
        brand = Brand(slug="post-test", name="測試品牌")
        session.add(brand)
        session.flush()
        account = Account(
            brand_id=brand.id, platform="instagram", external_id="test-ig", name="測試 IG"
        )
        other = Account(
            brand_id=brand.id, platform="facebook", external_id="test-fb", name="測試 FB"
        )
        session.add_all([account, other])
        session.flush()
        return {
            "headers": {"X-Api-Key": settings.ingest_api_key.get_secret_value()},
            "account_id": account.id,
            "other_id": other.id,
            "brand_id": brand.id,
        }


def post_body(at="2026-09-26T09:10:00+08:00"):
    return {
        "platform": "instagram",
        "account_external_id": "test-ig",
        "posts": [
            {
                "external_id": "test-post",
                "caption": "[測試] 貼文",
                "media_type": "IMAGE",
                "published_at": at,
                "permalink": "https://www.instagram.com/p/test-fixture/",
            }
        ],
    }


def metric_body():
    return {
        "platform": "instagram",
        "account_external_id": "test-ig",
        "metrics": [
            {
                "post_external_id": "test-post",
                "captured_at": "2026-09-26T02:20:00Z",
                "sync_slot": "2026-09-26T02:00:00Z",
                "views": 0,
                "reach": None,
                "extra_json": {"unavailable": {"reach": 100}},
            }
        ],
    }


def upsert_posts(client, body):
    return call_service(client, posts_service.upsert_posts, PostsInput, body)


def upsert_metrics(client, body):
    return call_service(client, posts_service.upsert_metrics, MetricsInput, body)


def test_posts_upsert_and_pending_comment_link(client, post_data):
    event = {
        "platform": "instagram",
        "account_external_id": "test-ig",
        "external_id": "comment-event",
        "signature_ok": True,
        "payload": {"test": True},
        "messages": [
            {
                "external_id": "test-comment",
                "thread_external_id": "test-post",
                "kind": "comment_thread",
                "post_external_id": "test-post",
                "contact": {"external_id": "test-fan"},
                "direction": "in",
                "author_type": "fan",
                "text": "[測試] 留言",
                "sent_at": "2026-09-26T09:11:00+08:00",
            }
        ],
    }
    assert deliver_event(client, event).status_code == 200
    first = upsert_posts(client, post_body())
    assert first.json()["linked_threads"] == 1
    again = upsert_posts(client, post_body())
    assert again.json()["linked_threads"] == 0
    with client.app.state.session_factory() as session:
        post = session.scalar(select(Post))
        assert post.version == 1
        assert post.published_at == datetime(2026, 9, 26, 1, 10, tzinfo=UTC)
        assert session.scalar(select(Thread)).post_id == post.id
    edited = post_body()
    edited["posts"][0]["caption"] = "[測試] 更新內文"
    assert (
        upsert_posts(client, edited).status_code
        == 200
    )
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Post)) == 1
        assert session.scalar(select(Post)).caption == "[測試] 更新內文"


def test_snapshot_parallel_retries_preserve_actual_time_and_null(client, post_data):
    upsert_posts(client, post_body())
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(
            pool.map(
                lambda _: upsert_metrics(client, metric_body()),
                range(8),
            )
        )
    assert all(r.status_code == 200 for r in responses)
    assert sum(r.json()["inserted"] for r in responses) == 1
    repeat = metric_body()
    repeat["metrics"][0]["captured_at"] = "2026-09-26T02:40:00Z"
    assert (
        upsert_metrics(client, repeat).json()[
            "inserted"
        ]
        == 0
    )
    with client.app.state.session_factory() as session:
        snapshot = session.scalar(select(MetricSnapshot))
        assert snapshot.captured_at.minute == 20 and snapshot.sync_slot.minute == 0
        assert snapshot.views == 0 and snapshot.reach is None and snapshot.shares is None
        assert snapshot.extra_json["unavailable"]["reach"] == 100


@pytest.mark.parametrize(
    "hours,tier", [(47.99, "hourly"), (48, "daily"), (335.99, "daily"), (336, "weekly")]
)
def test_age_boundaries(hours, tier):
    now = datetime(2026, 9, 26, tzinfo=UTC)
    assert schedule_tier(now - timedelta(hours=hours), now) == tier


@pytest.mark.parametrize("age,interval", [(1, 1), (72, 24), (480, 168)])
def test_due_frequency_uses_slots_after_restart(client, post_data, age, interval):
    now = datetime(2026, 9, 26, 2, tzinfo=UTC)
    upsert_posts(client, post_body((now - timedelta(hours=age)).isoformat()))
    upsert_metrics(client, metric_body())
    with client.app.state.session_factory() as session:
        assert not due_metrics(
            session, "instagram", "test-ig", 100, now + timedelta(hours=interval - 1)
        )["posts"]
        due = due_metrics(session, "instagram", "test-ig", 100, now + timedelta(hours=interval))[
            "posts"
        ]
        assert [p["external_id"] for p in due] == ["test-post"]


def test_account_boundaries(client, post_data):
    unknown = post_body()
    unknown["account_external_id"] = "unknown"
    assert (
        upsert_posts(client, unknown).status_code
        == 422
    )
    upsert_posts(client, post_body())
    other = metric_body()
    other.update(platform="facebook", account_external_id="test-fb")
    assert (
        upsert_metrics(client, other).status_code
        == 422
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("views", -1),
        ("views", True),
        ("views", "5"),
        ("captured_at", "2026-09-26"),
        ("sync_slot", "2026-09-26T02:01:00Z"),
        ("completion_rate", 1.1),
    ],
)
def test_invalid_metrics_rejected_without_echoing_payload(client, post_data, field, value):
    body = metric_body()
    body["metrics"][0][field] = value
    with pytest.raises(ValidationError) as error:
        MetricsInput.model_validate(body)
    assert repr(value) not in str(error.value)


def test_failed_batch_rolls_back(client, post_data):
    upsert_posts(client, post_body())
    body = metric_body()
    bad = copy.deepcopy(body["metrics"][0])
    bad["post_external_id"] = "missing-post"
    body["metrics"].append(bad)
    assert (
        upsert_metrics(client, body).status_code
        == 422
    )
    with client.app.state.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MetricSnapshot)) == 0


def test_post_list_brand_filter(client, post_data):
    upsert_posts(client, post_body())
    with client.app.state.session_factory.begin() as session:
        staff = Staff(username="test-reader", display_name="測試", role="viewer")
        session.add(staff)
        session.flush()
        access = BrandAccess(session, staff)
        assert list_posts(access, None, 100, 0) == []
        session.add(StaffBrand(staff_id=staff.id, brand_id=post_data["brand_id"]))
        session.flush()
        assert len(list_posts(access, None, 100, 0)) == 1


def test_post_override_precedes_brand_and_expires_to_default(client, post_data):
    upsert_posts(client, post_body("2020-01-01T00:00:00Z"))
    with client.app.state.session_factory.begin() as session:
        post = session.scalar(select(Post))
        account = session.get(Account, post.account_id)
        brand = Setting(key=f"schedule.brand.{account.brand_id}", value_json={"tier": "daily"})
        session.add(brand)
        set_schedule_override(session, post.id, "hourly", 2)
        setting = session.scalar(select(Setting).where(Setting.key == f"schedule.post.{post.id}"))
        expiry = datetime.fromisoformat(setting.value_json["expires_at"])
        assert effective_tier(session, account, post, expiry - timedelta(seconds=1)) == "hourly"
        assert effective_tier(session, account, post, expiry) == "daily"
        session.delete(brand)
        session.flush()
        assert effective_tier(session, account, post, expiry) == "weekly"
        with pytest.raises(ValueError):
            set_schedule_override(session, post.id, "hourly", 0)
