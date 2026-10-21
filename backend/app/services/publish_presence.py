"""偵測已在平台上刪除的貼文。

只以「完整清單中不存在」判定刪除：任何分頁失敗、分頁上限、格式異常都不判定。
不使用單篇查詢的錯誤判定（Facebook 對已刪除貼文回 code 10，與缺少權限相同，無法區分）。
"""

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app.db import ensure_write
from app.logging_config import log_failure
from app.models import Account, AuditLog, PublishPost, PublishTarget
from app.models.base import utc_now
from app.services import (
    credentials,
    posts,
    publish,
    publish_platforms,
    publish_rules,
    settings_store,
)

MIN_AGE = timedelta(minutes=10)
MANUAL_GAP = 60
PAGE_LIMIT = 50
NAMES = {
    "facebook": "Facebook",
    "instagram": "Instagram",
    "threads": "Threads",
    "youtube": "YouTube",
}
YOUTUBE_REASONS = {
    "youtube_auth_error": "YouTube 授權失效，請重新連結後再試",
    "youtube_permission_missing": "YouTube 權限不足，無法取得影片清單",
    "meta_rate_limited": "YouTube 額度已滿，請稍後再試",
    "meta_server_error": "YouTube 暫時無法回應，請稍後再試",
    "network_error": "無法連線到 YouTube，請稍後再試",
    "invalid_response": "YouTube 影片清單格式異常",
    "invalid_pagination": "YouTube 影片清單分頁格式異常",
    "discovery_limit": "YouTube 影片清單過長，無法取得完整清單",
    "work_budget": "YouTube 本輪呼叫已達上限，請稍後再試",
}
META_REASONS = {
    "meta_rate_limited": "Meta 呼叫配額已滿，請稍後再試",
    "meta_retry_required": "Meta 暫時無法回應，請稍後再試",
    "meta_timeout": "Meta 回應逾時，請稍後再試",
    "network_error": "無法連線到 Meta，請稍後再試",
    "posts_unavailable": "無法取得完整貼文清單",
    "invalid_pagination": "貼文清單分頁格式異常",
    "discovery_limit": "貼文清單過長，無法取得完整清單",
}


class Unjudgeable(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def eligible(session, platform, *, account=None, brand_id=None, now=None, kind=None):
    """成功、有平台貼文代號、發佈超過 10 分鐘的目標（含已刪除者，供重新出現時還原）。

    Facebook 依 kind 分三類：posts（貼文 ID，比對 /published_posts）、videos（影片 ID，
    比對 /videos）、drafts（存成 FB 草稿／未發佈，不在任何清單內，逐篇查詢）。
    """
    now = now or utc_now()
    query = (
        select(PublishTarget)
        .join(Account, Account.id == PublishTarget.account_id)
        .join(PublishPost, PublishPost.id == PublishTarget.post_id)
        .where(
            PublishPost.format != "story",
            PublishTarget.platform == platform,
            PublishTarget.status == "succeeded",
            PublishTarget.platform_post_id.is_not(None),
            PublishTarget.last_attempt_at <= now - MIN_AGE,
        )
        .order_by(PublishTarget.id)
    )
    if platform == "facebook" and kind is not None:
        query = query.where(PublishPost.facebook_unpublished.is_(kind == "drafts"))
    if account is not None:
        query = query.where(Account.external_id == account)
    if brand_id is not None:
        query = query.where(Account.brand_id == brand_id)
    rows = list(session.scalars(query))
    if platform == "facebook" and kind in {"posts", "videos"}:
        # Facebook 影片（一般影片與 Reels）記的是影片 ID，要和 /videos 清單比對；
        # 其餘格式記的是貼文 ID，和 /published_posts 比對。
        videos = kind == "videos"
        rows = [
            target
            for target in rows
            if (session.get(PublishPost, target.post_id).format == "video") is videos
        ]
    return rows


def apply(session, platform, account, ids, *, brand_id=None, now=None, kind=None, only=None):
    """以完整清單 ids 判定該帳號的目標；呼叫端須確保 ids 是完整清單。"""
    now = now or utc_now()
    result = {"checked": 0, "newly_deleted": 0, "restored": 0}
    targets = eligible(session, platform, account=account, brand_id=brand_id, now=now, kind=kind)
    for target in targets:
        if only is not None and target.id not in only:
            # 逐篇查詢沒有明確結果的目標不判定，也不記檢查時間。
            continue
        result["checked"] += 1
        target.presence_checked_at = now
        present = target.platform_post_id in ids
        post = session.get(PublishPost, target.post_id)
        if not present and target.deleted_at is None:
            target.deleted_at = now
            result["newly_deleted"] += 1
            publish.audit(
                session,
                post,
                "target.deleted",
                detail={"platform": platform, "post_id": target.platform_post_id},
            )
        elif present and target.deleted_at is not None:
            target.deleted_at = None
            result["restored"] += 1
            publish.audit(
                session,
                post,
                "target.restored",
                detail={"platform": platform, "post_id": target.platform_post_id},
            )
    return result


EMPTY = "平台回傳的貼文清單為空，為避免誤判不做判定"


def record(factory, platform, account, ids):
    """排程的 metrics() 以已取得的完整清單呼叫，不另外多打清單 API。"""
    if not ids:
        # 有發佈紀錄的帳號不會沒有任何貼文；空清單多半是權限或帳號異常，不能據此全部判定刪除。
        return None
    with factory.begin() as session:
        # 同一份完整清單也用來隱藏貼文數據裡已在平台刪除的貼文。
        posts.mark_missing(session, platform, account, set(ids))
        # metrics() 的 Facebook 清單是 /published_posts，只能判定貼文 ID 的目標。
        kind = "posts" if platform == "facebook" else None
        return apply(session, platform, account, set(ids), kind=kind)


def threads_listing(token):
    ids, after = set(), None
    with publish_platforms.client_factory() as client:
        for _ in range(PAGE_LIMIT):
            params = {"fields": "id", "limit": 100, **({"after": after} if after else {})}
            try:
                body = publish_platforms.request(
                    client, publish_platforms.TH, "me/threads", token, params=params
                )
            except publish_platforms.PlatformFailure as failure:
                raise Unjudgeable(
                    publish_rules.ERRORS.get(failure.code, "無法取得 Threads 貼文清單")
                ) from None
            data = body.get("data")
            if not isinstance(data, list) or any(
                not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in data
            ):
                raise Unjudgeable("Threads 貼文清單格式異常")
            ids.update(row["id"] for row in data)
            paging = body.get("paging")
            paging = paging if isinstance(paging, dict) else {}
            if not paging.get("next"):
                return ids
            cursors = paging.get("cursors")
            after = cursors.get("after") if isinstance(cursors, dict) else None
            if not isinstance(after, str) or not after or len(after) > 4096:
                raise Unjudgeable("Threads 貼文清單分頁格式異常")
    raise Unjudgeable("Threads 貼文清單過長，無法取得完整清單")


def meta_listing(workers, platform, account, edge=None):
    from app.services.gateway_workers import WorkerError

    ids, after = set(), None
    context = {"platform": platform, "account_external_id": account, "source": "metrics"}
    edge = edge or ("/published_posts" if platform == "facebook" else "/media")
    try:
        for _ in range(PAGE_LIMIT):
            query = {"fields": "id", "limit": 100, **({"after": after} if after else {})}
            response = workers.graph(account + edge, query, context)
            data = response.get("body") or {}
            if response["statusCode"] != 200 or data.get("error"):
                code = (data.get("error") or {}).get("code")
                retry = code in (4, 17, 32, 613, 190) or response["statusCode"] >= 500
                raise WorkerError("meta_retry_required" if retry else "posts_unavailable")
            rows = data.get("data")
            if not isinstance(rows, list) or any(
                not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in rows
            ):
                raise WorkerError("posts_unavailable")
            ids.update(row["id"] for row in rows)
            paging = data.get("paging") if isinstance(data.get("paging"), dict) else {}
            if not paging.get("next"):
                return ids
            cursors = paging.get("cursors")
            after = cursors.get("after") if isinstance(cursors, dict) else None
            if not isinstance(after, str) or not after or len(after) > 4096:
                raise WorkerError("invalid_pagination")
        raise WorkerError("discovery_limit")
    except WorkerError as error:
        raise Unjudgeable(META_REASONS.get(error.code, "無法取得完整貼文清單")) from None
    except Exception as error:
        log_failure("mwb.publish_presence", "publish_presence_listing_failed", error)
        raise Unjudgeable("無法取得完整貼文清單") from None


def draft_presence(workers, account, targets):
    """逐篇查詢 FB 草稿／未發佈目標：回傳 (存在的 ID, 不存在的 ID)，其餘不判定。

    不存在的影片回 100/33；不存在的貼文回 10，但 10 也可能是權限不足，
    所以先確認同一權杖讀得到粉專本身，才把 10 視為不存在。
    """
    from app.services.gateway_workers import WorkerError

    context = {"platform": "facebook", "account_external_id": account, "source": "metrics"}
    present, missing = set(), set()
    try:
        proof = workers.graph(account, {"fields": "id"}, context)
        if proof["statusCode"] != 200 or (proof.get("body") or {}).get("id") != account:
            raise Unjudgeable("無法確認 Facebook 權限，草稿不判定")
        for target in targets:
            identity = target.platform_post_id
            response = workers.graph(identity, {"fields": "id"}, context)
            body = response.get("body") or {}
            error = body.get("error") if isinstance(body.get("error"), dict) else None
            if response["statusCode"] == 200 and body.get("id") == identity:
                present.add(identity)
            elif error and (
                (error.get("code") == 100 and error.get("error_subcode") == 33)
                or error.get("code") == 10
            ):
                missing.add(identity)
    except WorkerError as error:
        raise Unjudgeable(META_REASONS.get(error.code, "無法查詢 Facebook 草稿")) from None
    except Unjudgeable:
        raise
    except Exception as error:
        log_failure("mwb.publish_presence", "publish_presence_listing_failed", error)
        raise Unjudgeable("無法查詢 Facebook 草稿") from None
    return present, missing


def youtube_listing(workers):
    """頻道 uploads 清單（含私人與不公開影片）；任何失敗都不判定。"""
    from app.services.gateway_workers import WorkerError
    from app.services.youtube import Sync

    try:
        return Sync(workers).uploaded_ids()
    except WorkerError as error:
        raise Unjudgeable(YOUTUBE_REASONS.get(error.code, "無法取得完整影片清單")) from None
    except Exception as error:
        log_failure("mwb.publish_presence", "publish_presence_listing_failed", error)
        raise Unjudgeable("無法取得完整影片清單") from None


def run(factory, settings, *, brand_id=None, platforms=tuple(NAMES), workers=None, now=None):
    """排程與手動共用的判定入口；FB／IG 重新抓完整清單（經 Meta 呼叫配額）。"""
    from app.services.gateway_workers import Workers

    now = now or utc_now()
    result = {"checked": 0, "newly_deleted": 0, "restored": 0, "unresolved": []}
    for platform in platforms:
        with factory() as session:
            accounts = sorted(
                {
                    session.get(Account, target.account_id).external_id
                    for target in eligible(session, platform, brand_id=brand_id, now=now)
                }
            )
            current = credentials.raw(
                credentials.resolve(publish.ID_KEYS[platform], settings, session)
            )
            token = credentials.raw(
                credentials.resolve(publish.TOKEN_KEYS[platform], settings, session)
            )
        if not accounts:
            continue

        def skip(reason, platform=platform):
            result["unresolved"].append({"platform": platform, "reason": reason})

        if not current:
            skip("平台尚未連結")
            continue
        if not token:
            skip("權杖缺失，請重新連結帳號")
            continue
        for account in accounts:
            if account != current:
                skip("發佈帳號已變更，無法判定")
                continue
            if platform == "facebook":
                workers = workers or Workers(factory, settings)
                for kind, edge in (("posts", "/published_posts"), ("videos", "/videos")):
                    with factory() as session:
                        if not eligible(session, platform, account=account,
                                        brand_id=brand_id, now=now, kind=kind):
                            continue
                    try:
                        ids = meta_listing(workers, platform, account, edge)
                    except Unjudgeable as error:
                        skip(error.reason)
                        continue
                    if not ids:
                        skip(EMPTY)
                        continue
                    with factory.begin() as session:
                        if kind == "posts":
                            posts.mark_missing(session, platform, account, ids)
                        counts = apply(session, platform, account, ids,
                                       brand_id=brand_id, now=now, kind=kind)
                    for key in ("checked", "newly_deleted", "restored"):
                        result[key] += counts[key]
                with factory() as session:
                    drafts = eligible(session, platform, account=account,
                                      brand_id=brand_id, now=now, kind="drafts")
                    session.expunge_all()
                if drafts:
                    try:
                        present, missing = draft_presence(workers, account, drafts[:PAGE_LIMIT])
                    except Unjudgeable as error:
                        skip(error.reason)
                        continue
                    judged = {t.id for t in drafts if t.platform_post_id in present | missing}
                    with factory.begin() as session:
                        counts = apply(session, platform, account, present,
                                       brand_id=brand_id, now=now, kind="drafts", only=judged)
                    for key in ("checked", "newly_deleted", "restored"):
                        result[key] += counts[key]
                continue
            try:
                if platform == "threads":
                    ids = threads_listing(token)
                elif platform == "youtube":
                    workers = workers or Workers(factory, settings)
                    ids = youtube_listing(workers)
                else:
                    workers = workers or Workers(factory, settings)
                    ids = meta_listing(workers, platform, account)
            except Unjudgeable as error:
                skip(error.reason)
                continue
            if not ids:
                skip(EMPTY)
                continue
            with factory.begin() as session:
                # 同一份完整清單也更新貼文數據的已刪除狀態。
                posts.mark_missing(session, platform, account, ids)
                counts = apply(session, platform, account, ids, brand_id=brand_id, now=now)
            for key in ("checked", "newly_deleted", "restored"):
                result[key] += counts[key]
    return result


def hourly_threads(factory, settings, covered=()):
    """排程每小時檢查 Threads；沒有可檢查的目標時不呼叫 API。

    metrics() 這一輪已經抓過完整 Threads 清單（covered 含 threads）並已判定時，不再多打一次。
    """
    if "threads" in covered:
        return None
    try:
        return run(factory, settings, platforms=("threads",))
    except Exception as error:
        log_failure("mwb.publish_presence", "publish_presence_threads_failed", error)
        return None


def manual(access, factory, settings, brand_id):
    access.require_brand(brand_id, write=True)
    session = access.session
    ensure_write(session)
    now = utc_now()
    key = f"publish.presence.manual.{brand_id}"
    row = settings_store.get(session, key)
    last = row.value_json.get("at") if row else None
    if last and (now.timestamp() - float(last)) < MANUAL_GAP:
        raise HTTPException(429, "剛檢查過，請稍後再試")
    settings_store.put(session, key, {"at": now.timestamp()}, row)
    session.commit()
    result = run(factory, settings, brand_id=brand_id)
    with factory.begin() as write:
        write.add(
            AuditLog(
                actor=f"staff:{access.staff.id}",
                brand_id=brand_id,
                action="publish.presence.check",
                target_type="brand",
                target_id=brand_id,
                detail_json={
                    "checked": result["checked"],
                    "newly_deleted": result["newly_deleted"],
                    "unresolved": [item["platform"] for item in result["unresolved"]],
                },
            )
        )
    return result
