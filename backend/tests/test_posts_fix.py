"""Pagination/date regressions; all fixtures are isolated and no platform calls occur."""

from datetime import UTC, datetime, timedelta

import pytest
from test_comment_poll import login
from test_comment_poll import poll_data as poll_data
from test_posts_batch2 import batch2 as batch2

from app.models import Message, Post, Thread
from app.services import date_ranges

START = datetime(2026, 9, 25, 16, tzinfo=UTC)
END = START + timedelta(days=1)


@pytest.fixture
def page_data(client, batch2):
    with client.app.state.session_factory.begin() as session:
        thread = Thread(
            brand_id=batch2["brand"],
            account_id=batch2["fb_account"],
            kind="comment_thread",
            post_id=batch2["fb_post"],
            external_id="page-fixture",
        )
        session.add(thread)
        session.flush()
        thread_id = thread.id
        for index in range(105):
            session.add(
                Message(
                    thread_id=thread.id,
                    external_id=f"root-{index}",
                    text="[測試] 主留言",
                    direction="in",
                    author_type="fan",
                    sent_at=START + timedelta(minutes=index),
                    comment_parent_known=True,
                )
            )
        session.flush()
        for index in range(3):
            session.add(
                Message(
                    thread_id=thread.id,
                    external_id=f"reply-{index}",
                    text="[測試] 回覆",
                    direction="out",
                    author_type="brand",
                    sent_at=START + timedelta(hours=3, minutes=index),
                    comment_parent_known=True,
                    comment_parent_id="root-104" if not index else f"reply-{index - 1}",
                )
            )
        for key, at in [
            ("before", START - timedelta(microseconds=1)),
            ("end", END),
            ("last", END - timedelta(microseconds=1)),
        ]:
            session.add(
                Message(
                    thread_id=thread.id,
                    external_id=key,
                    text="[測試] 日界線",
                    direction="in",
                    author_type="fan",
                    sent_at=at,
                    comment_parent_known=True,
                )
            )
    login(client, batch2, "marketing")
    return {
        **batch2,
        "thread": thread_id,
        "path": f"/api/posts/{batch2['fb_post']}/comment-threads",
    }


def test_default_page_has_50_newest_roots_and_complete_replies(client, page_data):
    page = client.get(page_data["path"]).json()
    assert len(page["root_ids"]) == 50
    assert page["total"] == 111 and page["range_total"] == 111 and page["root_total"] == 108
    assert page["next_offset"] == 50
    assert len(page["items"]) == 53
    assert {m["external_id"] for m in page["items"]} >= {
        "reply-0",
        "reply-1",
        "reply-2",
        "root-104",
    }
    assert "root-0" not in {m["external_id"] for m in page["items"]}
    by_id = {m["id"]: m for m in page["items"]}
    assert [by_id[i]["external_id"] for i in page["root_ids"][:3]] == ["end", "last", "root-104"]


def test_filter_and_pagination_include_only_taipei_day_without_gaps(client, page_data):
    path = page_data["path"] + "?period=custom&date_from=2026-09-26&date_to=2026-09-26"
    items, roots, offset = [], [], 0
    while offset is not None:
        result = client.get(path + f"&offset={offset}").json()
        assert result["total"] == 111 and result["range_total"] == 109
        assert result["root_total"] == 106
        items += result["items"]
        roots += result["root_ids"]
        offset = result["next_offset"]
    assert len(items) == len({m["id"] for m in items}) == 109
    assert len(roots) == len(set(roots)) == 106
    assert all(START <= datetime.fromisoformat(m["sent_at"]) < END for m in items)
    assert {"root-0", "last"} <= {m["external_id"] for m in items}
    assert not {"before", "end"} & {m["external_id"] for m in items}


def test_recent_reply_survives_out_of_range_parent_and_does_not_fetch_parent(client, page_data):
    with client.app.state.session_factory.begin() as session:
        session.add(
            Message(
                thread_id=page_data["thread"],
                external_id="new-reply",
                text="[測試] 近期回覆",
                direction="in",
                author_type="fan",
                sent_at=END,
                comment_parent_known=True,
                comment_parent_id="root-104",
            )
        )
    result = client.get(page_data["path"] + "?date_from=2026-09-27&date_to=2026-09-27").json()
    assert {m["external_id"] for m in result["items"]} == {"end", "new-reply"}
    assert result["root_total"] == result["range_total"] == 2


def test_post_dates_use_taipei_boundaries_and_paginate(client, page_data):
    with client.app.state.session_factory.begin() as session:
        session.get(Post, page_data["fb_post"]).published_at = START - timedelta(days=2)
        for index, at in enumerate(
            [START - timedelta(microseconds=1), START, END - timedelta(microseconds=1), END]
        ):
            session.add(
                Post(
                    account_id=page_data["fb_account"],
                    external_id=f"date-{index}",
                    caption="[測試] 發文日期",
                    media_type="POST",
                    published_at=at,
                )
            )
    path = "/api/posts?platform=facebook&date_from=2026-09-26&date_to=2026-09-26&limit=1"
    first = client.get(path).json()
    second = client.get(path + "&offset=1").json()
    assert first[0]["external_id"] == "date-2"
    assert second[0]["external_id"] == "date-1"
    assert client.get(path + "&offset=2").json() == []


@pytest.mark.parametrize("period", ["7", "30", "90"])
def test_quick_range_includes_today_and_uses_taipei_not_utc(period):
    now = datetime(2026, 9, 26, 16, 5, tzinfo=UTC)  # Taipei is already September 27.
    start, end = date_ranges.date_bounds(period, now=now)
    assert end == datetime(2026, 9, 27, 16, tzinfo=UTC)
    assert start == end - timedelta(days=int(period))


@pytest.mark.parametrize(
    "suffix",
    [
        "?period=wrong",
        "?date_from=no",
        "?date_from=2026-02-30",
        "?date_from=2026-09-27&date_to=2026-09-26",
        "?date_to=9999-12-31",
        "?date_from=0001-01-01",
        "?limit=0",
        "?limit=201",
        "?offset=-1",
    ],
)
def test_invalid_dates_and_pagination_rejected(client, page_data, suffix):
    assert client.get(page_data["path"] + suffix).status_code == 422
    assert client.get("/api/posts" + suffix).status_code == 422


def test_empty_and_open_ended_ranges(client, page_data):
    empty = client.get(page_data["path"] + "?date_from=2030-01-01").json()
    assert empty["items"] == [] and empty["next_offset"] is None and empty["range_total"] == 0
    old = client.get(page_data["path"] + "?date_to=2026-09-25").json()
    assert [m["external_id"] for m in old["items"]] == ["before"]
    assert date_ranges.date_bounds() == (None, None)


@pytest.mark.parametrize("focus_external", ["root-104", "reply-2"])
@pytest.mark.parametrize("date_query", ["date_from=2030-01-01", "period=7", "period=90"])
def test_linked_old_comment_includes_its_tree_without_widening_range(
    client, page_data, focus_external, date_query, monkeypatch
):
    monkeypatch.setattr(date_ranges, "utc_now", lambda: datetime(2030, 1, 1, tzinfo=UTC))
    with client.app.state.session_factory.begin() as session:
        focus_id = (
            session.query(Message)
            .filter_by(thread_id=page_data["thread"], external_id=focus_external)
            .one()
            .id
        )
    path = page_data["path"] + "?" + date_query
    assert client.get(path).json()["items"] == []
    response = client.get(path + f"&focus_id={focus_id}")
    assert response.status_code == 200
    result = response.json()
    assert {m["external_id"] for m in result["items"]} == {
        "root-104",
        "reply-0",
        "reply-1",
        "reply-2",
    }
    assert result["range_total"] == 0
    assert result["total"] == 111
    assert len(result["root_ids"]) == 1
    assert result["next_offset"] is None
    assert client.get(path + "&focus_id=999999").status_code == 404
    other = f"/api/posts/{page_data['fb_post'] + 1}/comment-threads?focus_id={focus_id}"
    assert client.get(other).status_code == 404


def test_linked_old_comment_keeps_filtered_page_and_pagination(client, page_data):
    with client.app.state.session_factory.begin() as session:
        focus_id = (
            session.query(Message)
            .filter_by(thread_id=page_data["thread"], external_id="root-0")
            .one()
            .id
        )
        session.add(
            Message(
                thread_id=page_data["thread"],
                external_id="newer-root",
                text="[測試] 新留言",
                direction="in",
                author_type="fan",
                sent_at=END + timedelta(hours=1),
                comment_parent_known=True,
            )
        )
    path = page_data["path"] + "?date_from=2026-09-27&limit=1"
    response = client.get(path + f"&focus_id={focus_id}")
    assert response.status_code == 200
    page = response.json()
    assert {m["external_id"] for m in page["items"]} == {"newer-root", "root-0"}
    assert page["range_total"] == 2 and page["next_offset"] == 1
    following = client.get(path + "&offset=1").json()
    assert {m["external_id"] for m in following["items"]} == {"end"}
    assert following["next_offset"] is None


def test_new_page_retains_brand_dm_isolation(client, page_data):
    with client.app.state.session_factory.begin() as session:
        dm = Thread(
            brand_id=page_data["brand"],
            account_id=page_data["fb_account"],
            kind="dm",
            post_id=page_data["fb_post"],
            external_id="private-fix",
        )
        session.add(dm)
        session.flush()
        session.add_all(
            [
                Message(
                    thread_id=dm.id,
                    external_id="dm",
                    text="[測試] 私訊",
                    direction="in",
                    author_type="fan",
                    sent_at=START,
                ),
                Message(
                    thread_id=dm.id,
                    external_id="brand-response",
                    text="[測試] 品牌回覆",
                    direction="in",
                    author_type="fan",
                    sent_at=START,
                ),
            ]
        )
    result = client.get(page_data["path"]).json()
    assert result["total"] == 111
    assert client.get(f"/api/posts/{page_data['posts'][-1]}/comment-threads").status_code == 404
    with client.app.state.session_factory() as session:
        for message in result["items"]:
            stored = session.get(Message, message["id"])
            assert stored.text == message["text"]
            assert session.get(Thread, stored.thread_id).kind == "comment_thread"


def test_same_timestamp_tie_break_and_corrupt_parent_relationships(client, page_data):
    with client.app.state.session_factory.begin() as session:
        for key, parent, known in [
            ("cycle-a", "cycle-b", True),
            ("cycle-b", "cycle-a", True),
            ("missing", "absent", True),
            ("unknown", "cycle-a", False),
        ]:
            session.add(
                Message(
                    thread_id=page_data["thread"],
                    external_id=key,
                    text="[測試] 關係",
                    direction="in",
                    author_type="fan",
                    sent_at=END + timedelta(days=1),
                    comment_parent_known=known,
                    comment_parent_id=parent,
                )
            )
    path = page_data["path"] + "?date_from=2026-09-28&limit=2"
    one = client.get(path).json()
    two = client.get(path + "&offset=2").json()
    assert one["root_total"] == 4
    assert len(one["items"]) == len(two["items"]) == 2
    assert one["root_ids"] + two["root_ids"] == sorted(
        one["root_ids"] + two["root_ids"], reverse=True
    )
    assert {m["external_id"] for m in one["items"] + two["items"]} == {
        "cycle-a",
        "cycle-b",
        "missing",
        "unknown",
    }


def test_date_filter_does_not_make_ambiguous_parent_look_unique(client, page_data):
    with client.app.state.session_factory.begin() as session:
        other = Thread(
            brand_id=page_data["brand"],
            account_id=page_data["fb_account"],
            kind="comment_thread",
            post_id=page_data["fb_post"],
            external_id="duplicate-parent",
        )
        session.add(other)
        session.flush()
        session.add_all(
            [
                Message(
                    thread_id=other.id,
                    external_id="root-104",
                    text="[測試] 範圍外重複 ID",
                    direction="in",
                    author_type="fan",
                    sent_at=START - timedelta(days=1),
                ),
                Message(
                    thread_id=page_data["thread"],
                    external_id="ambiguous-child",
                    text="[測試] 不猜父關係",
                    direction="in",
                    author_type="fan",
                    sent_at=START,
                    comment_parent_known=True,
                    comment_parent_id="root-104",
                ),
            ]
        )
    result = client.get(
        page_data["path"] + "?date_from=2026-09-26&date_to=2026-09-26&limit=200"
    ).json()
    by_external = {m["external_id"]: m for m in result["items"]}
    assert by_external["ambiguous-child"]["id"] in result["root_ids"]
    assert by_external["reply-0"]["id"] in result["root_ids"]
    assert result["range_total"] == 110


def test_comment_page_requires_login(client, batch2):
    assert client.get(f"/api/posts/{batch2['fb_post']}/comment-threads").status_code == 401
