from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

from pydantic import SecretStr
from sqlalchemy import func, select
from test_comment_poll import login
from test_comment_poll import poll_data as poll_data

from app.models import Account, AudienceInsight, MetaApiCall
from app.services import meta_api
from app.services.workers import Workers
from app.services.workers import audience as worker_audience
from app.services.workers.base import WorkerError

NOW = datetime(2026, 10, 5, 2, tzinfo=UTC)  # Monday, Taipei 10:00.


def demographics(breakdown, results):
    return {
        "data": [
            {
                "name": "follower_demographics",
                "period": "lifetime",
                "total_value": {
                    "breakdowns": [
                        {
                            "dimension_keys": ["timeframe", breakdown],
                            "results": [
                                {"dimension_values": ["THIS_MONTH", key], "value": value}
                                for key, value in results
                            ],
                        }
                    ]
                },
            }
        ]
    }


ONLINE = {
    "data": [
        {
            "name": "online_followers",
            "period": "lifetime",
            "values": [
                # 太平洋夏令時間 10/3 的 0 時＝台北 10/3 15 時。
                {"value": {"0": 40, "1": 20}, "end_time": "2026-10-04T07:00:00+0000"},
                {"value": {"0": 60, "1": 0}, "end_time": "2026-10-05T07:00:00+0000"},
                {"value": {}, "end_time": "2026-10-06T07:00:00+0000"},
            ],
        }
    ]
}

PAGE = {
    "data": [
        {
            "name": "page_follows_country",
            "period": "day",
            "values": [
                {"value": {"TW": 1}, "end_time": "2026-10-03T07:00:00+0000"},
                {"value": {"TW": 90, "HK": 7}, "end_time": "2026-10-04T07:00:00+0000"},
            ],
        },
        {
            "name": "page_follows_city",
            "period": "day",
            "values": [{"value": {"Taipei, Taiwan": 50}, "end_time": "2026-10-04T07:00:00+0000"}],
        },
    ]
}


def setup(client, settings, monkeypatch, responses):
    settings.meta_page_id, settings.meta_ig_account_id = "333", "111"
    settings.meta_page_access_token = SecretStr("isolated-test-token")
    monkeypatch.setattr(meta_api, "utc_now", lambda: NOW)
    factory = client.app.state.session_factory
    with factory.begin() as session:
        account = session.scalar(select(Account).where(Account.external_id == "111"))
        session.add(
            Account(
                brand_id=account.brand_id, platform="facebook", external_id="333", name="[測試] FB"
            )
        )
    calls = []

    def request(method, url, **kwargs):
        assert method == "GET" and url.startswith("https://graph.facebook.com/v26.0/")
        qs = kwargs["qs"]
        calls.append((url.split("v26.0/", 1)[1], qs))
        key = qs.get("breakdown") or qs["metric"]
        status, body = responses(url, key)
        return {"statusCode": status, "headers": {}, "body": body}

    worker = Workers(factory, settings, request=request, clock=lambda: NOW.timestamp())
    monkeypatch.setattr(worker, "threads_account", lambda registered=False: None)
    monkeypatch.setattr(worker, "youtube_account", lambda: None)
    return factory, worker, calls


def ok(url, key):
    if "/333/" in url:
        return 200, PAGE
    if key == "online_followers":
        return 200, ONLINE
    sample = {
        "age": [("25-34", 30), ("18-24", 50)],
        "gender": [("F", 70), ("M", 10)],
        "country": [("TW", 75), ("HK", 5)],
        "city": [("Taipei, Taiwan", 40)],
    }
    return 200, demographics(key, sample[key])


def stored(factory, external_id):
    with factory() as session:
        account = session.scalar(select(Account).where(Account.external_id == external_id))
        return {
            (row.metric, row.breakdown): row
            for row in session.scalars(
                select(AudienceInsight).where(AudienceInsight.account_id == account.id)
            )
        }


def test_instagram_and_facebook_daily_once(client, poll_data, settings, monkeypatch):
    factory, worker, calls = setup(client, settings, monkeypatch, ok)
    assert worker.audience() == {"saved": 7, "errors": []}
    assert len(calls) == 6
    ig = stored(factory, "111")
    assert ig["followers", "age"].items_json == [
        {"key": "18-24", "value": 50},
        {"key": "25-34", "value": 30},
    ]
    assert ig["followers", "gender"].items_json[0] == {"key": "F", "value": 70}
    assert ig["followers", "country"].period == "this_month"
    online = ig["online", "hour"]
    assert online.status == "ready" and len(online.items_json) == 24
    assert {"key": "15", "value": 50} in online.items_json
    assert {"key": "16", "value": 10} in online.items_json
    demo_qs = next(qs for _, qs in calls if qs.get("breakdown") == "age")
    assert demo_qs == {
        "metric": "follower_demographics",
        "period": "lifetime",
        "timeframe": "this_month",
        "breakdown": "age",
        "metric_type": "total_value",
    }
    fb = stored(factory, "333")
    assert fb["followers", "country"].items_json == [
        {"key": "TW", "value": 90},
        {"key": "HK", "value": 7},
    ]
    assert fb["followers", "city"].items_json == [{"key": "Taipei, Taiwan", "value": 50}]
    assert ("followers", "age") not in fb
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(MetaApiCall)) == 6
    # 同一天再跑不再呼叫平台；空跑回 0，排程不寫稽核。
    assert worker.audience() == 0
    assert len(calls) == 6
    worker.clock = lambda: (NOW + timedelta(days=1)).timestamp()
    monkeypatch.setattr(meta_api, "utc_now", lambda: NOW + timedelta(days=1))
    assert worker.audience()["saved"] == 7
    assert len(calls) == 12


def test_platform_refusals_become_hints_not_errors(client, poll_data, settings, monkeypatch):
    def refuse(url, key):
        if "/333/" in url:
            return 400, {"error": {"code": 100, "message": "invalid metric"}}
        if key == "online_followers":
            return 200, {"data": []}
        if key == "city":
            return 400, {"error": {"code": 10, "message": "permission"}}
        return 200, {"data": []}

    factory, worker, _ = setup(client, settings, monkeypatch, refuse)
    assert worker.audience() == {"saved": 7, "errors": []}
    ig = stored(factory, "111")
    assert ig["followers", "age"].status == "unavailable"
    assert ig["followers", "age"].error == "no_data"
    assert ig["followers", "city"].error == "permission_missing"
    assert ig["online", "hour"].status == "unavailable"
    fb = stored(factory, "333")
    assert {row.error for row in fb.values()} == {"not_available"}


def test_rate_limit_saves_nothing_and_stops_meta(client, poll_data, settings, monkeypatch):
    def limited(url, key):
        return 400, {"error": {"code": 4}}

    factory, worker, calls = setup(client, settings, monkeypatch, limited)
    result = worker.audience()
    assert result["saved"] == 0
    assert result["errors"][0]["code"] == "meta_rate_limited"
    # 限流後同一輪不再呼叫其他 Meta 帳號。
    assert len(calls) == 1
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(AudienceInsight)) == 0


def test_malformed_response_saves_nothing(client, poll_data, settings, monkeypatch):
    def broken(url, key):
        body = demographics("age", [("18-24", 5)])
        body["data"][0]["total_value"]["breakdowns"][0]["results"][0]["value"] = -1
        return 200, body

    factory, worker, _ = setup(client, settings, monkeypatch, broken)
    result = worker.audience()
    assert result["errors"] == [{"platform": "instagram", "code": "invalid_response"}]
    assert stored(factory, "111") == {}


def test_threads_demographics_and_missing_permission(client, poll_data, settings, monkeypatch):
    factory, worker, _ = setup(client, settings, monkeypatch, ok)
    settings.meta_page_access_token = SecretStr("")
    with factory.begin() as session:
        account = session.scalar(select(Account).where(Account.external_id == "111"))
        session.add(
            Account(
                brand_id=account.brand_id, platform="threads", external_id="555", name="[測試] TH"
            )
        )
    monkeypatch.setattr(worker, "threads_account", lambda registered=False: ("555", "tok"))
    monkeypatch.setattr(worker, "threads_access", lambda: "granted")
    seen = []

    def threads_get(path, query, token):
        seen.append((path, query))
        if query["breakdown"] == "city":
            raise WorkerError("meta_api_error", detail=100)
        return demographics(query["breakdown"], [("x", 1)])

    monkeypatch.setattr(worker, "threads_get", threads_get)
    assert worker.audience() == {"saved": 4, "errors": []}
    assert seen[0] == (
        "555/threads_insights",
        {"metric": "follower_demographics", "breakdown": "age"},
    )
    rows = stored(factory, "555")
    assert rows["followers", "city"].error == "not_available"
    assert rows["followers", "age"].status == "ready"

    blocked = Mock()
    monkeypatch.setattr(worker, "threads_block", blocked)
    worker.clock = lambda: (NOW + timedelta(days=1)).timestamp()

    def denied(path, query, token):
        raise WorkerError("threads_permission_missing")

    monkeypatch.setattr(worker, "threads_get", denied)
    assert worker.audience() == 0
    blocked.assert_called_once()
    # 權限錯誤不覆寫前一天的資料。
    assert stored(factory, "555")["followers", "age"].status == "ready"


class FakeYouTube:
    channel_id = "UCtest"

    def __init__(self, responses):
        self.responses, self.queries = responses, []

    def get(self, edge, query, work=None):
        assert edge == "reports"
        self.queries.append(query)
        return self.responses(query)


def test_youtube_viewer_age_gender_and_country(client, poll_data, settings, monkeypatch):
    factory, worker, _ = setup(client, settings, monkeypatch, ok)
    settings.meta_page_access_token = SecretStr("")
    with factory.begin() as session:
        account = session.scalar(select(Account).where(Account.external_id == "111"))
        session.add(
            Account(
                brand_id=account.brand_id, platform="youtube", external_id="UCtest", name="[測試]"
            )
        )

    def reports(query):
        if query["dimensions"] == "country":
            return {
                "columnHeaders": [{"name": "country"}, {"name": "views"}],
                "rows": [["TW", 900], ["JP", 30]],
            }
        return {
            "columnHeaders": [
                {"name": "ageGroup"},
                {"name": "gender"},
                {"name": "viewerPercentage"},
            ],
            "rows": [
                ["age25-34", "female", 40.0],
                ["age18-24", "female", 20.0],
                ["age25-34", "male", 30.0],
                ["age18-24", "male", 10.0],
            ],
        }

    fake = FakeYouTube(reports)
    monkeypatch.setattr(worker, "youtube_account", lambda: "UCtest")
    monkeypatch.setattr(worker, "youtube_sync", lambda: fake)
    assert worker.audience() == {"saved": 3, "errors": []}
    # 太平洋時間 10/4，往前兩天的資料才完整：9/5–10/2 共 28 天。
    assert fake.queries[0]["startDate"] == "2026-09-05"
    assert fake.queries[0]["endDate"] == "2026-10-02"
    rows = stored(factory, "UCtest")
    assert rows["viewers", "age"].items_json == [
        {"key": "18-24", "value": 30.0},
        {"key": "25-34", "value": 70.0},
    ]
    assert rows["viewers", "age"].unit == "percent"
    assert rows["viewers", "gender"].items_json[0] == {"key": "female", "value": 60.0}
    assert rows["viewers", "country"].items_json[0] == {"key": "TW", "value": 900}

    def missing(query):
        raise WorkerError("youtube_permission_missing")

    fake.responses = missing
    worker.clock = lambda: (NOW + timedelta(days=1)).timestamp()
    assert worker.audience()["saved"] == 3
    assert stored(factory, "UCtest")["viewers", "age"].error == "permission_missing"


def test_online_hours_follow_pacific_daylight_saving():
    winter = {
        "data": [
            {
                "name": "online_followers",
                "values": [{"value": {"0": 8}, "end_time": "2026-12-02T08:00:00+0000"}],
            }
        ]
    }
    items = worker_audience.online_items(winter)
    # 太平洋標準時間 0 時＝台北 16 時。
    assert {"key": "16", "value": 8} in items


def test_api_reads_local_rows_with_brand_scope(client, poll_data, settings, monkeypatch):
    factory, worker, _ = setup(client, settings, monkeypatch, ok)
    worker.audience()
    graph = Mock(side_effect=AssertionError("query must not call Meta"))
    monkeypatch.setattr(Workers, "graph", graph)
    assert client.get("/api/dashboard/audience").status_code == 401
    for role, count in (("admin", 3), ("viewer", 2)):
        login(client, poll_data, role)
        body = client.get("/api/dashboard/audience").json()
        assert body["timezone"] == "Asia/Taipei"
        assert len(body["accounts"]) == count
        ig = next(a for a in body["accounts"] if a["platform"] == "instagram")
        assert {(i["metric"], i["breakdown"]) for i in ig["insights"]} == {
            ("followers", "age"),
            ("followers", "gender"),
            ("followers", "country"),
            ("followers", "city"),
            ("online", "hour"),
        }
        client.post("/api/auth/logout")
    login(client, poll_data, "viewer")
    other = poll_data["brand"] + 1
    assert client.get(f"/api/dashboard/audience?brand_id={other}").status_code == 404
    graph.assert_not_called()
