"""Golden transcripts captured from the passing baseline Node suites at dab0205.
Every envelope, pagination request, usage record and checkpoint is compared, not only status.
Comment transcripts now require field expansion and exclude automatic discovery.
Only wall-clock capture/duration fields are normalized; platform timestamps remain exact.
Legacy DM transcripts now verify signed discard and the absence of the DM worker.
Worker transcripts record internal persistence as direct service calls ("service", "args",
"result") in the original order; arguments are compared after the same schema validation the
service receives, so field values, explicit nulls and omitted fields still must match exactly.
"""

import base64
import copy
import hmac
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.schemas.meta import ApiCallFinish, ApiCallStart, PollCheckpoint, PollClaim, PollFinish
from app.schemas.posts import MetricsInput, PostsInput
from app.services import (
    comment_poll,
    ingest,
    meta_api,
    posts,
    publish_presence,
    tiktok,
    youtube,
)
from app.services.gateway_workers import Workers
from app.services.webhook_normalize import meta_envelopes

ORACLE = json.loads(
    (Path(__file__).parent / "fixtures/workflow_oracle.json").read_text(encoding="utf-8-sig")
)


def scrub(value):
    if isinstance(value, dict):
        return {
            k: ("<clock>" if k in ("duration_ms", "captured_at") else scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


# 服務名稱 → (模組, 函式名, 參數 schema)；schema 為 None 表示參數不是 schema 物件。
SERVICES = {
    "meta_api.start_call": (meta_api, "start_call", ApiCallStart),
    "meta_api.finish_call": (meta_api, "finish_call", ApiCallFinish),
    "comment_poll.claim": (comment_poll, "claim", PollClaim),
    "comment_poll.checkpoint": (comment_poll, "checkpoint", PollCheckpoint),
    "comment_poll.finish": (comment_poll, "finish", PollFinish),
    "posts.upsert_posts": (posts, "upsert_posts", PostsInput),
    "posts.upsert_metrics": (posts, "upsert_metrics", MetricsInput),
    "posts.due_metrics": (posts, "due_metrics", None),
    "ingest.events": (ingest, "events", None),
}


def without_new_comments(actual, expected):
    """留言增量同步在進度中新增 new_comments（本次新增留言數）；舊紀錄沒有此欄位。
    單獨驗證其型別與範圍，其餘欄位仍須與紀錄完全一致。"""
    if (
        isinstance(actual, dict)
        and isinstance(actual.get("progress"), dict)
        and "new_comments" in actual["progress"]
        and "new_comments" not in ((expected or {}).get("progress") or {})
    ):
        actual = copy.deepcopy(actual)
        added = actual["progress"].pop("new_comments")
        assert isinstance(added, int) and added >= 0, added
    return actual


NORMAL = [
    r
    for r in ORACLE
    if r["name"] in ("line-inbound", "meta-inbound")
    and any(c["request"]["url"].endswith("/ingest/events") for c in r["calls"])
]


@pytest.mark.parametrize(
    "row", NORMAL, ids=[r["name"] + "-" + str(i) for i, r in enumerate(NORMAL)]
)
def test_normalization_matches_node_every_field(row):
    payload = json.loads(base64.b64decode(row["raw"]))
    expected = [
        c["request"]["body"] for c in row["calls"] if c["request"]["url"].endswith("/ingest/events")
    ]
    if row["name"] == "line-inbound":
        from app.services.webhooks import receive

        raw = base64.b64decode(row["raw"])
        key = "isolated-oracle-signature"
        headers = {
            "x-line-signature": base64.b64encode(hmac.digest(key.encode(), raw, "sha256")).decode()
        }

        def no_database():
            pytest.fail("Discarded LINE events must not open a database")

        result = receive(
            no_database,
            SimpleNamespace(line_channel_secret=SecretStr(key)),
            "line-inbound",
            raw,
            headers,
        )
        assert result == (200, {"ok": True, "events": 0}, [])
        return
    else:
        result = meta_envelopes(
            payload, row["env"]["META_PAGE_ID"], row["env"]["META_IG_ACCOUNT_ID"]
        )
    if row["name"] == "meta-inbound":
        expected = [
            e
            for e in expected
            if not any("messaging" in entry for entry in e["payload"].get("entry", []))
        ]
    assert result == expected


WORKERS = [
    r
    for r in ORACLE
    if r["name"] in ("meta-comments", "meta-dm-backfill", "meta-sync", "notify") and r["calls"]
]


@pytest.mark.parametrize(
    "row", WORKERS, ids=[r["name"] + "-" + str(i) for i, r in enumerate(WORKERS)]
)
def test_workers_match_node_complete_transcript(row, monkeypatch):
    if row["name"] == "meta-dm-backfill":
        assert not hasattr(Workers, "dm")
        return
    calls = copy.deepcopy(row["calls"])
    seen = []
    env = row["env"]
    settings = SimpleNamespace(
        meta_page_id=env.get("META_PAGE_ID", ""),
        meta_ig_account_id=env.get("META_IG_ACCOUNT_ID", ""),
        meta_page_access_token=SecretStr(env.get("META_PAGE_ACCESS_TOKEN", "")),
        notify_line_channel_access_token=SecretStr(env.get("NOTIFY_LINE_CHANNEL_ACCESS_TOKEN", "")),
    )

    def consume(method, url, body=None, qs=None, headers=None, **kwargs):
        assert calls, (method, url, body)
        call = calls.pop(0)
        assert "service" not in call, (call["service"], method, url)
        expected = call["request"]
        seen.append(expected)
        assert (method, url) == (expected["method"], expected["url"])
        body = without_new_comments(body, expected.get("body"))
        assert scrub(body) == scrub(expected.get("body"))
        assert qs == expected.get("qs")
        assert url.startswith("https:")
        assert headers == expected["headers"]
        assert expected["disableFollowRedirect"] is True
        if call.get("error"):
            raise RuntimeError("isolated network failure")
        return call["response"]

    def service(name):
        _, _, schema = SERVICES[name]

        def call(session, *args, **kwargs):
            assert calls, name
            expected = calls.pop(0)
            assert expected.get("service") == name, (expected.get("service"), name)
            seen.append(expected)
            if name == "posts.due_metrics":
                platform, account, limit = args
                actual = {"platform": platform, "account_external_id": account, "limit": limit}
                assert actual == expected["args"]
                return expected["result"]
            if name == "ingest.events":
                raw, source = args
                assert source == expected["source"] and kwargs == {"settings": settings}
                assert scrub(json.loads(raw)) == scrub(expected["args"])
                result = expected["result"]
                return SimpleNamespace(
                    status=200,
                    result=SimpleNamespace(
                        processed=result["processed"], model_dump=lambda mode: dict(result)
                    ),
                )
            body = args[0]
            assert isinstance(body, schema), (name, type(body))
            # 時間欄位依 schema 正規化後比較：service 收到的就是這份資料。
            dumped = body.model_dump(mode="json", exclude_unset=True)
            reference = schema.model_validate(expected["args"]).model_dump(
                mode="json", exclude_unset=True
            )
            assert scrub(without_new_comments(dumped, reference)) == scrub(reference)
            return expected["result"]

        return call

    for name, (module, attribute, _) in SERVICES.items():
        monkeypatch.setattr(module, attribute, service(name))
    # 舊版以 factory=None 執行；改用空 session 後仍不得觸及 YouTube 或已刪除偵測的資料庫。
    monkeypatch.setattr(youtube, "account", lambda *a: None)
    monkeypatch.setattr(tiktok, "account", lambda *a: None)
    presence = []
    monkeypatch.setattr(
        publish_presence, "record", lambda factory, *a: presence.append(a)
    )
    worker = Workers(
        lambda: nullcontext(), settings, request=consume, clock=lambda: row["now"] / 1000
    )
    if row["name"] == "meta-comments":
        options = (
            json.loads(base64.b64decode(row["raw"]))
            if row["input"].get("headers")
            else {"requested_only": env.get("META_COMMENTS_REQUESTED_ONLY") == "true"}
        )
        result = worker.comments(**options)
    else:
        result = getattr(
            worker,
            {"meta-dm-backfill": "dm", "meta-sync": "metrics", "notify": "notifications"}[
                row["name"]
            ],
        )()
    assert not calls, (len(calls), result)
    if row.get("error") == "meta_sync_failed":
        assert result["ok"] is False
    else:
        expected = row["result"].get("body", row["result"])
        assert result == expected
