"""Durable publication state machine; no outbound action in a database write transaction."""

import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import wait as wait_all
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import or_, select

from app.db import ensure_write
from app.logging_config import log_failure
from app.models import (
    Account,
    AuditLog,
    NotificationDelivery,
    PublishLink,
    PublishMedia,
    PublishPost,
    PublishTarget,
)
from app.models.base import utc_now
from app.services import (
    credentials,
    ideation,
    notify,
    oauth,
    publish_platforms,
    publish_rules,
    publish_tiktok,
    publish_youtube,
    roles,
    settings_store,
    tiktok_oauth,
    youtube_oauth,
)
from app.services.publish_media import create_link, path_for, remove_files
from app.services.redact import redact

ID_KEYS = {
    "facebook": "META_PAGE_ID",
    "instagram": "META_IG_ACCOUNT_ID",
    "threads": "THREADS_USER_ID",
    "youtube": "YOUTUBE_CHANNEL_ID",
    "tiktok": "TIKTOK_OPEN_ID",
}
TOKEN_KEYS = {
    "facebook": "META_PAGE_ACCESS_TOKEN",
    "instagram": "META_PAGE_ACCESS_TOKEN",
    "threads": "THREADS_ACCESS_TOKEN",
    "youtube": "YOUTUBE_ACCESS_TOKEN",
    "tiktok": "TIKTOK_ACCESS_TOKEN",
}
STATUS = {"done": "發佈成功", "partial": "部分成功", "failed": "發佈失敗", "missed": "已錯過"}
# 排程到期的貼文在這裡發佈，不佔用排程執行緒：一篇大型上傳（YouTube、IG 等待容器）
# 不會拖過五分鐘，讓同時到期的其他貼文還沒嘗試就被標成已錯過。locked_at 防止重複執行。
_scheduled = ThreadPoolExecutor(max_workers=4, thread_name_prefix="publish-scheduled")


def enabled(session):
    row = settings_store.get(session, "publishing.enabled")
    return bool(row and row.value_json.get("enabled") is True)


def audit(session, post, action, actor="system:publish", detail=None):
    detail = dict(detail or {})
    if post and post.agent_publish_json and action in {"attempt", "result", "missed"}:
        actor = f"staff:{post.agent_publish_json['staff_id']}"
        detail["via"] = post.agent_publish_json["via"]
    session.add(
        AuditLog(
            actor=actor,
            brand_id=post.brand_id if post else None,
            action="publish." + action,
            target_type="publish_post",
            target_id=post.id if post else None,
            detail_json=detail or {},
        )
    )


def media_rows(session, identity):
    # 只含發佈素材；YouTube 縮圖（role=thumbnail）與 IG 封面（role=cover）不是素材，不在此列。
    return list(
        session.scalars(
            select(PublishMedia)
            .where(
                PublishMedia.post_id == identity,
                PublishMedia.deleted_at.is_(None),
                PublishMedia.role == "media",
            )
            .order_by(PublishMedia.position, PublishMedia.id)
        )
    )


def bound_row(session, post, platform, key, role):
    identity = (post.platform_options_json or {}).get(platform, {}).get(key)
    if not identity:
        return None
    row = session.get(PublishMedia, identity)
    if not row or row.post_id != post.id or row.deleted_at or row.role != role:
        return None
    return row


def thumbnail_row(session, post):
    return bound_row(session, post, "youtube", "thumbnail_media_id", "thumbnail")


def cover_row(session, post):
    return bound_row(session, post, "instagram", "cover_media_id", "cover")


def facebook_cover_row(session, post):
    return bound_row(session, post, "facebook", "cover_media_id", "fb_cover")


def image_view(row):
    if not row:
        return None
    return {
        "id": row.id,
        "name": row.original_name,
        "mime": row.mime,
        "size": row.size,
        "width": row.width,
        "height": row.height,
    }


def instagram_sent(session, post):
    # IG 已送出（或發佈中）後封面不能再換，否則畫面與平台上的 Reels 不一致。
    return any(
        t.platform == "instagram" and t.status in {"succeeded", "publishing"}
        for t in targets(session, post.id)
    )


def public_detail(target):
    """對瀏覽器隱藏上傳工作階段網址；縮圖失敗另附中文原因。"""
    detail = {key: value for key, value in target.detail_json.items() if key != "upload"}
    thumbnail = detail.get("thumbnail")
    if isinstance(thumbnail, dict) and thumbnail.get("status") == "failed":
        errors = publish_rules.THUMBNAIL_ERRORS
        detail["thumbnail"] = {
            **thumbnail,
            "reason": errors.get(thumbnail.get("code"), errors["unknown"]),
        }
    cover = detail.get("cover")
    if isinstance(cover, dict) and cover.get("status") == "failed":
        errors = publish_rules.FB_COVER_ERRORS
        detail["cover"] = {**cover, "reason": errors.get(cover.get("code"), errors["unknown"])}
    return detail


def targets(session, identity):
    return list(
        session.scalars(
            select(PublishTarget)
            .where(PublishTarget.post_id == identity)
            .order_by(PublishTarget.id)
        )
    )


def locked(post, now=None):
    return post.status == "publishing" or (
        post.status in {"scheduled", "paused"}
        and post.scheduled_at is not None
        and post.scheduled_at <= (now or utc_now()) + timedelta(minutes=1)
    )


def get(access, identity, *, include_drafts=False):
    post = access.session.scalar(access.statement(PublishPost).where(PublishPost.id == identity))
    if not post:
        raise HTTPException(404, "找不到貼文")
    if (
        not include_drafts
        and not roles.can(access, "publish.edit")
        and post.status
        in {
            "draft",
            "scheduled",
            "paused",
            "cancelled",
        }
    ):
        raise HTTPException(404, "找不到發佈紀錄")
    return post


def editable(access, identity):
    post = get(access, identity)
    access.require_brand(post.brand_id, write=True)
    if locked(post) or post.status not in {"draft", "scheduled", "paused", "missed", "cancelled"}:
        raise HTTPException(409, "貼文已鎖定或已送出，不可編輯")
    return post


def story_results(session, target):
    from app.services.publish_story_insights import results

    return results(session, target)


def view(session, post):
    return {
        "id": post.id,
        "brand_id": post.brand_id,
        "format": post.format,
        "caption": post.caption,
        "captions": post.captions_json,
        "platforms": post.platforms_json,
        "facebook_unpublished": bool(post.facebook_unpublished),
        "platform_options": publish_rules.platform_options(post),
        "effective_platform_options": publish_rules.effective_options(post),
        "warnings": [],
        "status": post.status,
        "source": post.source,
        "agent_source": {"agent": post.source_json.get("agent")} if post.source_json else None,
        "publish_via": post.agent_publish_json.get("via"),
        "report_id": post.report_id,
        "idea_index": post.idea_index,
        "scheduled_at": post.scheduled_at,
        "locked": locked(post),
        "version": post.version,
        "created_at": post.created_at,
        "updated_at": post.updated_at,
        "media": [
            {
                "id": m.id,
                "name": m.original_name,
                "mime": m.mime,
                "size": m.size,
                "width": m.width,
                "height": m.height,
                "duration": m.duration,
            }
            for m in media_rows(session, post.id)
        ],
        "thumbnail": image_view(thumbnail_row(session, post)),
        "cover": image_view(cover_row(session, post)),
        "facebook_cover": image_view(facebook_cover_row(session, post)),
        "targets": [
            {
                "platform": t.platform,
                "status": t.status,
                "permalink": t.permalink,
                "error_code": t.error_code,
                "reason": publish_rules.ERRORS.get(t.error_code, ""),
                "attempts": t.attempts,
                "deleted_at": t.deleted_at,
                "presence_checked_at": t.presence_checked_at,
                "platform_post_id": t.platform_post_id,
                "detail": public_detail(t),
                "stories": story_results(session, t) if post.format == "story" else [],
            }
            for t in targets(session, post.id)
        ],
    }


def listing(access, brand_id=None, report_id=None, *, include_drafts=False):
    if brand_id:
        access.require_brand(brand_id)
    query = access.statement(PublishPost, brand_id).order_by(
        PublishPost.updated_at.desc(), PublishPost.id.desc()
    )
    if report_id is not None:
        query = query.where(
            PublishPost.report_id == report_id,
            PublishPost.source == "ideation",
            PublishPost.status.in_(["draft", "scheduled", "paused", "missed"]),
        )
    else:
        recent = access.statement(PublishPost, brand_id).with_only_columns(PublishPost.id)
        recent = recent.order_by(PublishPost.id.desc()).limit(200)
        query = query.where(or_(PublishPost.status == "draft", PublishPost.id.in_(recent)))
    if not include_drafts and not roles.can(access, "publish.edit"):
        query = query.where(PublishPost.status.in_(["done", "partial", "failed", "missed"]))
    return [
        view(access.session, post)
        for post in access.session.scalars(query)
        if post.status != "draft"
        or post.caption.strip()
        or post.platforms_json
        or any(value.strip() for value in post.captions_json.values())
        or media_rows(access.session, post.id)
    ]


def accounts(session, settings, brand_id):
    result = {}
    for platform, name in ID_KEYS.items():
        identity = credentials.raw(credentials.resolve(name, settings, session))
        result[platform] = (
            session.scalar(
                select(Account).where(
                    Account.brand_id == brand_id,
                    Account.platform == platform,
                    Account.external_id == identity,
                )
            )
            if identity
            else None
        )
    return result


def options(access, settings, brand_id):
    access.require_brand(brand_id)
    readiness = oauth.publish_readiness(access.session, settings, cached=True)
    rows = accounts(access.session, settings, brand_id)
    return {
        "enabled": enabled(access.session),
        "rules": publish_rules.rules_view(),
        "default_platform_options": publish_rules.form_defaults(),
        "platforms": {
            p: {
                "ready": bool(rows[p]) and readiness[p]["ready"],
                "name": rows[p].name if rows[p] else "未連結",
                "reasons": readiness[p]["reasons"] + ([] if rows[p] else ["此品牌尚未連結帳號"]),
                # 已連結但缺少上傳權限：發佈頁引導重新連結，而不是顯示「尚未連結」。
                **({"hint": readiness[p]["hint"]} if readiness[p].get("hint") else {}),
                # FB 已連結但缺 pages_manage_engagement：可以發佈，只有自訂封面不會套用。
                **(
                    {"cover_hint": readiness[p]["cover_hint"]}
                    if readiness[p].get("cover_hint")
                    else {}
                ),
            }
            for p in ID_KEYS
        },
    }


def save(access, body, identity=None, *, agent_source=None):
    session = access.session
    ensure_write(session)
    access.require_brand(body.brand_id, write=True)
    if identity is None:
        post = PublishPost(brand_id=body.brand_id, creator_id=access.staff.id, format=body.format)
        session.add(post)
        session.flush()
    else:
        post = editable(access, identity)
        if post.version != body.version:
            raise HTTPException(409, "貼文已更新，請重新整理")
        if post.brand_id != body.brand_id:
            raise HTTPException(422, "不可更換貼文品牌")
        # 部分成功後重新排程再取消會回到草稿；Facebook 已送出（或發佈中）就不能改公開方式。
        if body.facebook_unpublished != bool(post.facebook_unpublished) and any(
            t.platform == "facebook" and t.status in {"succeeded", "publishing"}
            for t in targets(session, post.id)
        ):
            raise HTTPException(409, "Facebook 已發佈，不可變更公開方式")
        rows = media_rows(session, post.id)
        if set(body.media_ids) != {m.id for m in rows} or len(set(body.media_ids)) != len(rows):
            raise HTTPException(422, "媒體順序不完整")
        for m in rows:
            m.position = body.media_ids.index(m.id)
    if (
        identity is not None
        and any(
            t.status in {"succeeded", "publishing"} or t.detail_json.get("stories")
            for t in targets(session, post.id)
        )
        and (post.format == "story" or body.format == "story")
    ):
        raise HTTPException(409, "限時動態已部分發佈，不可變更素材、平台或格式")
    if body.format == "story" and len(media_rows(session, post.id)) > 10:
        raise HTTPException(422, "限時動態最多 10 則")
    # 空白的平台文案等於沒有覆寫（沿用共用文案），不存進草稿。
    captions = {platform: text for platform, text in body.captions.items() if text.strip()}
    previous_options = publish_rules.platform_options(post)
    options = deepcopy(publish_rules.DEFAULT_OPTIONS) if identity is None else previous_options
    options = deepcopy(options)
    supplied = (
        body.platform_options.model_dump(exclude_unset=True, exclude_none=True)
        if body.platform_options
        else {}
    )
    for platform, values in supplied.items():
        options[platform].update(values)
    threads = options["threads"]
    if "segments" in supplied.get("threads", {}) and "segments_custom" not in supplied["threads"]:
        threads["segments_custom"] = True
    if not threads["segments_custom"]:
        # 未手動指定回覆：Threads 文案原樣當第一則，超過上限由發佈規則提示，不自動拆段。
        threads["segments"] = [captions.get("threads", body.caption)]
    for target in targets(session, post.id):
        # 影片已在 YouTube 建立（video_id）但目標失敗：選項不能再改，否則重試不會套用到那支影片。
        sent = target.status in {"succeeded", "publishing"} or bool(
            target.detail_json.get("segment_ids") or target.detail_json.get("video_id")
        )
        if sent and options[target.platform] != previous_options[target.platform]:
            raise HTTPException(
                409, f"{publish_rules.NAMES[target.platform]} 已發佈，不可變更平台選項或分段"
            )
    post.platform_options_json = options
    post.format, post.caption = body.format, body.caption
    post.captions_json, post.platforms_json = captions, list(dict.fromkeys(body.platforms))
    post.facebook_unpublished = body.facebook_unpublished
    if agent_source:
        post.source_json = agent_source
        if post.source != "ideation":
            post.source = "agent"
    post.updated_at = utc_now()
    audit(
        session,
        post,
        "save",
        f"staff:{access.staff.id}",
        {"via": agent_source["agent"]} if agent_source else None,
    )
    session.commit()
    return view(session, post)


def idea_caption(idea, ending=""):
    tags = []
    for word in re.split(r"[\s、,，/／]+", idea.get("keyword", "")):
        # Unicode letters and numbers remain; punctuation, underscores and repeated # do not.
        clean = "".join(char for char in word if char.isalnum())
        tag = "#" + clean
        if clean and tag not in tags:
            tags.append(tag)
        if len(tags) == 5:
            break
    return "\n\n".join(
        part
        for part in (idea.get("title", ""), idea.get("hook", ""), ending, " ".join(tags))
        if part
    )


def idea_material(access, report_id, idea_index):
    report = ideation.get(access, report_id)
    access.require_brand(report.brand_id, write=True)
    ideas = report.data_json.get("ideas", [])
    if idea_index < 0 or idea_index >= len(ideas):
        raise HTTPException(404, "找不到主題")
    if report.status != "ready":
        raise HTTPException(409, "主題處理中，完成後才能建立草稿")
    return report, ideas[idea_index]


def from_idea(access, settings, body, *, caption=None, agent_source=None):
    session = access.session
    # Acquire the write lock before lookup so concurrent clicks reuse the same draft.
    ensure_write(session)
    report, idea = idea_material(access, body.report_id, body.idea_index)
    existing = session.scalar(
        select(PublishPost)
        .where(
            PublishPost.brand_id == report.brand_id,
            PublishPost.source == "ideation",
            PublishPost.report_id == report.id,
            PublishPost.idea_index == body.idea_index,
            PublishPost.status.in_(["draft", "scheduled", "paused", "missed"]),
        )
        .order_by(PublishPost.id.desc())
    )
    if existing:
        return {"post": view(session, existing), "created": False}
    ready = options(access, settings, report.brand_id)["platforms"]
    post = PublishPost(
        brand_id=report.brand_id,
        creator_id=access.staff.id,
        status="draft",
        format="video",
        source="ideation",
        report_id=report.id,
        idea_index=body.idea_index,
        source_json=agent_source or {},
        # 初稿只由主題的標題、開場與 hashtag 組成，不呼叫 AI；內容由人或 Agent 再修改。
        caption=caption if caption is not None else idea_caption(idea),
        platforms_json=[platform for platform, value in ready.items() if value["ready"]],
    )
    post.platform_options_json = deepcopy(publish_rules.DEFAULT_OPTIONS)
    post.platform_options_json["threads"]["segments"] = [post.caption]
    session.add(post)
    session.flush()
    audit(
        session,
        post,
        "from_idea",
        f"staff:{access.staff.id}",
        {
            "report_id": report.id,
            "idea_index": body.idea_index,
            **({"via": agent_source["agent"]} if agent_source else {}),
        },
    )
    session.commit()
    return {"post": view(session, post), "created": True}


def rule_check(post, platform, media, thumbnail, cover=None):
    platform_options = publish_rules.platform_options(post)[platform]
    if platform == "threads":
        platform_options["segments"] = publish_rules.threads_segments(post)
    return publish_rules.check(
        platform,
        post.format,
        publish_rules.platform_caption(post, platform),
        media,
        platform_options,
        unpublished=post.facebook_unpublished,
        thumbnail=thumbnail if platform == "youtube" else None,
        cover=cover if platform in {"instagram", "facebook"} else None,
    )


def checks(access, settings, identity, *, include_drafts=False):
    post = get(access, identity, include_drafts=include_drafts)
    opts = options(access, settings, post.brand_id)
    media = media_rows(access.session, post.id)
    thumbnail = thumbnail_row(access.session, post)
    covers = {
        "instagram": cover_row(access.session, post),
        "facebook": facebook_cover_row(access.session, post),
    }
    result = {}
    for p in ID_KEYS:
        item = rule_check(post, p, media, thumbnail, covers.get(p))
        item["ready"] = opts["platforms"][p]["ready"]
        item["reasons"] += opts["platforms"][p]["reasons"]
        item["ok"] = item["ok"] and item["ready"]
        result[p] = item
    return result


def remove_media(access, settings, identity, media_id):
    ensure_write(access.session)
    post = editable(access, identity)
    if post.format == "story" and any(
        t.detail_json.get("stories") for t in targets(access.session, identity)
    ):
        raise HTTPException(409, "限時動態已部分發佈，不可移除素材")
    media = access.session.get(PublishMedia, media_id)
    if not media or media.post_id != post.id or media.deleted_at:
        raise HTTPException(404, "找不到媒體")
    if media.role == "cover" and instagram_sent(access.session, post):
        raise HTTPException(409, "Instagram 已發佈，不可變更封面")
    media.deleted_at = utc_now()
    bound = {"cover": "instagram", "fb_cover": "facebook"}.get(media.role)
    if bound:
        options = deepcopy(post.platform_options_json or {})
        values = dict(options.get(bound, {}))
        if values.get("cover_media_id") == media.id:
            options[bound] = {**values, "cover_media_id": None}
            post.platform_options_json = options
    if media.role == "thumbnail":
        options = deepcopy(post.platform_options_json or {})
        youtube = dict(options.get("youtube", {}))
        if youtube.get("thumbnail_media_id") == media.id:
            options["youtube"] = {**youtube, "thumbnail_media_id": None}
            post.platform_options_json = options
    post.updated_at = utc_now()
    # Metadata commits first; a file cleanup failure must not restore a removed attachment.
    access.session.commit()
    remove_files(settings, media)
    return view(access.session, post)


def preview(access, settings, identity, media_id):
    post = get(access, identity)
    media = access.session.get(PublishMedia, media_id)
    if not media or media.post_id != post.id or media.deleted_at:
        raise HTTPException(404, "找不到媒體")
    return FileResponse(path_for(settings, media), media_type=media.mime)


def cancel(access, identity, *, delete=False, via=None):
    ensure_write(access.session)
    post = editable(access, identity)
    if delete and post.status != "draft":
        raise HTTPException(409, "只能刪除草稿")
    post.status, post.scheduled_at = "cancelled" if delete else "draft", None
    release_pending(access.session, post)
    audit(
        access.session,
        post,
        "delete" if delete else "cancel",
        f"staff:{access.staff.id}",
        {"via": via} if via else None,
    )
    access.session.commit()
    return view(access.session, post)


def release_pending(session, post, keep=()):
    """不會在這一輪送出的 pending 目標：從未嘗試就移除，嘗試過就回到失敗。

    execute() 會送出所有 pending 目標；留著的話，取消後改選平台或只重試失敗平台時，
    不在這次範圍的平台也會被送出。回到失敗後「只重試失敗平台」才看得到它們。
    """
    for target in targets(session, post.id):
        if target.platform in keep or target.status != "pending":
            continue
        if target.attempts == 0:
            session.delete(target)
        else:
            # prepare() 已清掉上次的錯誤碼；補一個代碼讓畫面說得出為何回到失敗。
            target.status, target.error_code = "failed", target.error_code or "cancelled"
    session.flush()


def queue_notice(session, post):
    policy, _, _ = notify.load_policy(session, post.brand_id)
    if not policy.enabled or not policy.group_id:
        return
    title = redact(post.caption[:30]).text.replace("\n", " ")
    lines = [f"發佈通知｜{title}｜{STATUS.get(post.status, post.status)}"]
    for t in targets(session, post.id):
        result = (
            "已錯過" if post.status == "missed" else "成功" if t.status == "succeeded" else "失敗"
        )
        if t.platform == "tiktok" and t.status == "succeeded":
            # 送到收件匣不等於公開；提醒到 App 內完成發佈。
            result = "已送到收件匣，請在 App 內完成發佈"
        lines.append(f"{t.platform}：{result}" + (f" {t.permalink}" if t.permalink else ""))
    session.add(
        NotificationDelivery(
            brand_id=post.brand_id,
            retry_key=str(uuid4()),
            recipient=policy.group_id,
            messages_json=[{"type": "text", "text": "\n".join(lines)}],
            next_attempt_at=utc_now(),
        )
    )


def set_enabled(access, body):
    session = access.session
    ensure_write(session)
    if not roles.can(access, "settings.manage"):
        raise HTTPException(403, "此帳號沒有這項功能的權限")
    row = settings_store.get(session, "publishing.enabled")
    settings_store.put(session, "publishing.enabled", {"enabled": body.enabled}, row)
    now = utc_now()
    for post in session.scalars(
        select(PublishPost).where(PublishPost.status == ("paused" if body.enabled else "scheduled"))
    ):
        post.status = (
            "paused" if not body.enabled else ("scheduled" if post.scheduled_at > now else "missed")
        )
        if post.status == "missed":
            queue_notice(session, post)
            release_pending(session, post)
    audit(session, None, "switch", f"staff:{access.staff.id}", {"enabled": body.enabled})
    session.commit()
    return {"enabled": body.enabled}


def validate_prepare(access, settings, identity, body, *, retry=False):
    session = access.session
    # Rule checks use only persisted OAuth evidence. Actual send rechecks with OAuth.
    results = checks(access, settings, identity)
    post = get(access, identity)
    access.require_brand(post.brand_id, write=True)
    if not enabled(session):
        raise HTTPException(409, "發佈功能未開啟")
    if post.version != body.version or locked(post):
        raise HTTPException(409, "貼文已更新或鎖定，請重新整理")
    if post.status not in {
        "draft",
        "scheduled",
        "paused",
        "missed",
        "failed",
        "partial",
        "cancelled",
    }:
        raise HTTPException(409, "目前狀態無法發佈")
    previous = targets(session, identity)
    # 重試也只限目前勾選的平台：取消排程後可能已把失敗的平台移除。
    selected = (
        [t.platform for t in previous if t.status == "failed" and t.platform in post.platforms_json]
        if retry
        else post.platforms_json
    )
    succeeded = {t.platform for t in previous if t.status == "succeeded"}
    selected = [p for p in selected if p not in succeeded]
    if not selected:
        raise HTTPException(422, "請選擇符合規則且帳號已就緒的平台")
    failures = [
        reason for p in selected if not results[p]["ok"] for reason in results[p]["reasons"]
    ]
    if failures:
        raise HTTPException(422, "；".join(failures))
    if body.scheduled_at and body.scheduled_at <= utc_now() + timedelta(minutes=1):
        raise HTTPException(422, "排程須在一分鐘之後")
    rows = accounts(session, settings, post.brand_id)
    for target in previous:
        if target.platform in selected and (
            target.detail_json.get("segment_ids") or target.detail_json.get("stories")
        ):
            if not rows[target.platform] or rows[target.platform].id != target.account_id:
                raise HTTPException(409, "已部分發佈，不可更換帳號")
    return post, previous, selected, rows


def prepare(access, settings, identity, body, *, retry=False, via=None):
    session = access.session
    ensure_write(session)
    post, previous, selected, rows = validate_prepare(access, settings, identity, body, retry=retry)
    # Editing a cancelled schedule may remove a platform before its first attempt.
    for target in previous:
        if target.platform not in post.platforms_json and target.attempts == 0:
            session.delete(target)
    # 不在這次範圍的 pending 目標不能留著，否則 execute() 會一併送出。
    release_pending(session, post, keep=selected)
    previous = targets(session, identity)
    for p in selected:
        target = next((t for t in previous if t.platform == p), None)
        if target is None:
            session.add(PublishTarget(post_id=identity, platform=p, account_id=rows[p].id))
        else:
            target.status, target.error_code, target.account_id = "pending", None, rows[p].id
    post.scheduled_at = body.scheduled_at
    post.locked_at = None
    post.status = "scheduled" if body.scheduled_at else "publishing"
    post.agent_publish_json = {"staff_id": access.staff.id, "via": via} if via else {}
    audit(
        session,
        post,
        "schedule" if body.scheduled_at else "confirm",
        f"staff:{access.staff.id}",
        {"via": via} if via else None,
    )
    session.commit()
    return view(session, post)


def finish(session, post):
    rows = targets(session, post.id)
    successful = sum(t.status == "succeeded" for t in rows)
    partial = successful or any(t.detail_json.get("stories") for t in rows)
    post.status = "done" if successful == len(rows) else "partial" if partial else "failed"
    if post.status == "done":
        post.completed_at = utc_now()
    audit(session, post, "result", detail={"status": post.status})
    queue_notice(session, post)


def execute(factory, settings, identity):
    with factory.begin() as session:
        post = session.get(PublishPost, identity)
        if not post or post.status != "publishing" or post.locked_at is not None:
            return
        post.locked_at = utc_now()
        ids = [t.id for t in targets(session, identity) if t.status == "pending"]
    try:
        # 各平台同時發佈，總時間約等於最慢的平台；每個目標各自開短交易，互不共用 session。
        if ids:
            with ThreadPoolExecutor(max_workers=len(ids), thread_name_prefix="publish") as pool:
                jobs = [
                    pool.submit(execute_target, factory, settings, identity, target_id)
                    for target_id in ids
                ]
            # 等全部平台結束後再拋出非預期錯誤，避免一個平台出錯就漏掉其他平台的結果。
            for job in jobs:
                job.result()
    finally:
        # 非預期錯誤也一定結算：還停在 pending／publishing 的目標結果不明，標失敗並提醒
        # 到平台確認；否則貼文會一直卡在發佈中，直到重新啟動。
        with factory.begin() as session:
            post = session.get(PublishPost, identity)
            if post.status == "publishing":
                for target in targets(session, identity):
                    if target.status in {"pending", "publishing"}:
                        target.status, target.error_code = "failed", "unknown"
                finish(session, post)
            succeeded = any(t.status == "succeeded" for t in targets(session, identity))
    if succeeded:
        request_metrics(settings)


def request_metrics(settings):
    # 有平台發佈成功就立刻排一輪成效同步，新貼文不必等到下一個整點才出現在貼文數據。
    from app.services.scheduler import scheduler_for

    try:
        scheduler = scheduler_for(settings)
        if scheduler:
            scheduler.request("metrics")
    except Exception as error:
        log_failure("mwb.publish", "publish_metrics_request_failed", error)


def execute_target(factory, settings, identity, target_id):
    with factory() as session:
        # OAuth may perform a read-only permission refresh; no write lock spans its HTTP call.
        try:
            readiness = oauth.publish_readiness(session, settings)
        except Exception:
            readiness = {p: {"ready": False} for p in ID_KEYS}
    link_ids = []
    try:
        with factory.begin() as session:
            post, target = session.get(PublishPost, identity), session.get(PublishTarget, target_id)
            if target.status != "pending" or post.status != "publishing":
                return
            if not enabled(session):
                target.status, target.error_code = "failed", "interrupted"
                return
            account = session.get(Account, target.account_id)
            credential_id = credentials.raw(
                credentials.resolve(ID_KEYS[target.platform], settings, session)
            )
            if (
                not readiness[target.platform]["ready"]
                or not account
                or account.brand_id != post.brand_id
            ):
                target.status, target.error_code = "failed", "not_ready"
                return
            if account.external_id != credential_id:
                target.status, target.error_code = "failed", "account_changed"
                return
            media = media_rows(session, identity)
            # 排程後仍可編輯：送出前依目前內容再檢查一次，
            # 不符規則就不送（例如格式改成影片但素材是圖片）。
            thumbnail = thumbnail_row(session, post) if target.platform == "youtube" else None
            covers = {"instagram": cover_row, "facebook": facebook_cover_row}
            cover = (
                covers[target.platform](session, post)
                if target.platform in {"instagram", "facebook"} and post.format == "video"
                else None
            )
            if not rule_check(post, target.platform, media, thumbnail, cover)["ok"]:
                target.status, target.error_code = "failed", "rules_failed"
                return
            token = credentials.raw(
                credentials.resolve(TOKEN_KEYS[target.platform], settings, session)
            )
            urls, cover_url = [], None
            category = youtube_oauth.category(session) if target.platform == "youtube" else None
            if (
                target.platform not in {"facebook", "youtube", "tiktok"}
                and post.format != "story"
                and not target.detail_json.get("segment_ids")
            ):
                try:
                    for m in media:
                        link_id, url = create_link(
                            session, settings, m, jpeg=target.platform == "instagram"
                        )
                        link_ids.append(link_id)
                        urls.append(url)
                    if cover and target.platform == "instagram":
                        # 封面和影片一樣用限時公開連結讓 Meta 下載；
                        # PNG 轉 JPEG（cover_url 只收 JPEG）。
                        link_id, cover_url = create_link(session, settings, cover, jpeg=True)
                        link_ids.append(link_id)
                except HTTPException:
                    target.status, target.error_code = "failed", "media_rejected"
                    return
            target.status, target.last_attempt_at = "publishing", utc_now()
            target.attempts += 1
            audit(
                session,
                post,
                "attempt",
                detail={"platform": target.platform, "attempt": target.attempts},
            )
    except Exception as error:
        # 送出前的交易出錯（主金鑰更換後無法解密、資料庫忙碌、轉檔失敗等）：還沒送出任何
        # 東西，另開短交易記成失敗，讓這一輪正常結算。
        log_failure("mwb.publish", "publish_target_prepare_failed", error)
        with factory.begin() as session:
            row = session.get(PublishTarget, target_id)
            if row.status == "pending":
                row.status, row.error_code = "failed", "unknown"
        return

    def revoke(link_ids=link_ids):
        # 撤銷失敗不能蓋掉發佈結果（否則成功的平台會被當成失敗而重送）；
        # 連結本身 15 分鐘到期，重新啟動時 recover() 也會全部撤銷。
        try:
            with factory.begin() as session:
                for link_id in link_ids:
                    session.get(PublishLink, link_id).revoked_at = utc_now()
        except Exception as error:
            log_failure("mwb.publish", "publish_link_revoke_failed", error)

    def checkpoint(detail, first_id, permalink, target_id=target_id):
        # HTTP 完成後才開短寫入交易，每段確認的 ID 在下一段 HTTP 前持久化。
        with factory.begin() as session:
            row = session.get(PublishTarget, target_id)
            if row.status != "publishing":
                raise publish_platforms.PlatformFailure("interrupted")
            row.detail_json = detail
            row.platform_post_id, row.permalink = first_id, permalink

    def story_url(item, link_ids=link_ids):
        try:
            with factory.begin() as session:
                link_id, url = create_link(
                    session, settings, item, jpeg=target.platform == "instagram"
                )
        except HTTPException:
            raise publish_platforms.PlatformFailure("media_rejected") from None
        link_ids.append(link_id)
        return url

    error, result = None, None
    try:
        if target.platform == "youtube":
            # 存取權杖可能已過期；由 youtube_oauth 換發（此時不持有任何寫入交易）。
            try:
                token = youtube_oauth.access_token(factory, settings)
            except oauth.ProviderFailure:
                raise publish_platforms.PlatformFailure("token_invalid") from None
        if target.platform == "tiktok":
            # access token 只有 24 小時，送出前由 tiktok_oauth 換發（不持有寫入交易）。
            try:
                token = tiktok_oauth.access_token(factory, settings)
            except oauth.ProviderFailure:
                raise publish_platforms.PlatformFailure("token_invalid") from None
        result = publish_platforms.publish(
            settings,
            target.platform,
            account.external_id,
            token,
            post,
            media,
            urls,
            revoke,
            progress=target.detail_json,
            checkpoint=checkpoint,
            story_url=story_url,
            thumbnail=thumbnail,
            cover_url=cover_url,
            category=category,
            quota=lambda kind: publish_youtube.reserve(factory, kind),
        )
    except publish_platforms.PlatformFailure as failure:
        error = failure.code
    except Exception:
        error = "unknown"
    finally:
        revoke()
    with factory.begin() as session:
        target = session.get(PublishTarget, target_id)
        if target.status != "publishing":
            return
        target.status, target.error_code = ("failed", error) if error else ("succeeded", None)
        if result:
            target.platform_post_id, target.permalink = result
        platform = target.platform
    if platform == "facebook" and cover is not None and not error and result:
        # 貼文已成功並保存後才套用封面：封面失敗只記在 detail，不會讓貼文變失敗或重送影片。
        outcome = publish_platforms.apply_facebook_cover(settings, token, result[0], cover)
        with factory.begin() as session:
            row = session.get(PublishTarget, target_id)
            row.detail_json = {**row.detail_json, "cover": outcome}


def reapply_thumbnail(access, factory, settings, identity):
    """只重設縮圖：影片已成功，絕不重傳影片。"""
    session = access.session
    post = get(access, identity)
    access.require_brand(post.brand_id, write=True)
    if not enabled(session):
        raise HTTPException(409, "發佈功能未開啟")
    target = next((t for t in targets(session, identity) if t.platform == "youtube"), None)
    thumbnail = thumbnail_row(session, post)
    if (
        not target
        or target.status != "succeeded"
        or not target.platform_post_id
        or not isinstance(target.detail_json.get("thumbnail"), dict)
        or target.detail_json["thumbnail"].get("status") != "failed"
    ):
        raise HTTPException(409, "沒有需要重新套用的縮圖")
    if target.deleted_at:
        raise HTTPException(409, "影片已在 YouTube 刪除")
    if thumbnail is None:
        raise HTTPException(409, "找不到縮圖檔案")
    account = session.get(Account, target.account_id)
    readiness = oauth.publish_readiness(session, settings, cached=True)["youtube"]
    channel = credentials.raw(credentials.resolve(ID_KEYS["youtube"], settings, session))
    if not readiness["ready"] or not account or account.external_id != channel:
        raise HTTPException(409, "YouTube 帳號尚未就緒，請檢查平台連線")
    target_id, video, brand = target.id, target.platform_post_id, post.brand_id
    session.commit()
    try:
        token = youtube_oauth.access_token(factory, settings)
        publish_youtube.reserve(factory, "thumbnail")
        outcome = publish_youtube.apply_thumbnail(settings, token, video, thumbnail)
    except oauth.ProviderFailure:
        outcome = {"status": "failed", "code": "token_invalid"}
    except publish_platforms.PlatformFailure as failure:
        outcome = {"status": "failed", "code": failure.code}
    with factory.begin() as write:
        row = write.get(PublishTarget, target_id)
        row.detail_json = {**row.detail_json, "thumbnail": outcome}
        write.add(
            AuditLog(
                actor=f"staff:{access.staff.id}",
                brand_id=brand,
                action="publish.youtube.thumbnail",
                target_type="publish_post",
                target_id=identity,
                detail_json={"status": outcome["status"], "code": outcome.get("code")},
            )
        )
    session.expire_all()
    return view(session, session.get(PublishPost, identity))


def reapply_facebook_cover(access, factory, settings, identity):
    """只重新套用 FB 封面：影片已成功，絕不重傳影片。"""
    session = access.session
    post = get(access, identity)
    access.require_brand(post.brand_id, write=True)
    if not enabled(session):
        raise HTTPException(409, "發佈功能未開啟")
    target = next((t for t in targets(session, identity) if t.platform == "facebook"), None)
    cover = facebook_cover_row(session, post)
    if (
        not target
        or target.status != "succeeded"
        or not target.platform_post_id
        or post.format != "video"
        or not isinstance(target.detail_json.get("cover"), dict)
        or target.detail_json["cover"].get("status") != "failed"
    ):
        raise HTTPException(409, "沒有需要重新套用的封面")
    if target.deleted_at:
        raise HTTPException(409, "影片已在 Facebook 刪除")
    if cover is None:
        raise HTTPException(409, "找不到封面檔案")
    account = session.get(Account, target.account_id)
    readiness = oauth.publish_readiness(session, settings, cached=True)["facebook"]
    page = credentials.raw(credentials.resolve(ID_KEYS["facebook"], settings, session))
    if not readiness["ready"] or not account or account.external_id != page:
        raise HTTPException(409, "Facebook 帳號尚未就緒，請檢查平台連線")
    token = credentials.raw(credentials.resolve(TOKEN_KEYS["facebook"], settings, session))
    target_id, video, brand = target.id, target.platform_post_id, post.brand_id
    session.commit()
    outcome = publish_platforms.apply_facebook_cover(settings, token, video, cover)
    # HTTP 之後另開寫入交易並重新讀取，不沿用請求開頭的讀取快照與舊物件。
    with factory.begin() as write:
        row = write.get(PublishTarget, target_id)
        row.detail_json = {**row.detail_json, "cover": outcome}
        write.add(
            AuditLog(
                actor=f"staff:{access.staff.id}",
                brand_id=brand,
                action="publish.facebook.cover",
                target_type="publish_post",
                target_id=identity,
                detail_json={"status": outcome["status"], "code": outcome.get("code")},
            )
        )
    session.expire_all()
    return view(session, session.get(PublishPost, identity))


def recover(factory):
    with factory.begin() as session:
        for post in session.scalars(select(PublishPost).where(PublishPost.status == "publishing")):
            for target in targets(session, post.id):
                if target.status in {"pending", "publishing"}:
                    target.status, target.error_code = "failed", "interrupted"
            finish(session, post)
        for link in session.scalars(select(PublishLink).where(PublishLink.revoked_at.is_(None))):
            link.revoked_at = utc_now()


def run_scheduled(factory, settings, identity):
    try:
        execute(factory, settings, identity)
    except Exception as error:
        # execute() 已先結算貼文；這裡只記錄，不影響其他到期貼文。
        log_failure("mwb.publish", "publish_scheduled_failed", error)


def tick(factory, settings, now=None, *, wait=False):
    """wait=True 等這一輪送出的貼文全部結束（測試用）；排程器不等，下一分鐘照常執行。"""
    now = now or utc_now()
    due = []
    with factory.begin() as session:
        for post in session.scalars(select(PublishPost).where(PublishPost.status == "scheduled")):
            if not enabled(session):
                post.status = "paused"
            elif post.scheduled_at < now - timedelta(minutes=5):
                post.status = "missed"
                queue_notice(session, post)
                release_pending(session, post)
                audit(session, post, "missed")
            elif post.scheduled_at <= now:
                post.status, post.locked_at = "publishing", None
                due.append(post.id)
            elif post.scheduled_at <= now + timedelta(minutes=1):
                post.locked_at = post.scheduled_at - timedelta(minutes=1)
    jobs = [_scheduled.submit(run_scheduled, factory, settings, identity) for identity in due]
    if wait:
        wait_all(jobs)
    cleaned = cleanup_media(factory, settings, now)
    try:
        inbox = publish_tiktok.refresh(factory, settings, now, failed=finish)
    except Exception:
        # 追蹤是否已在 App 發佈只影響顯示，失敗不能中斷排程發佈。
        inbox = 0
    return {"ok": True, "published": len(due), "cleaned": cleaned, "tiktok_checked": inbox}


def cleanup_media(factory, settings, now):
    count = 0
    with factory.begin() as session:
        for media in session.scalars(
            select(PublishMedia)
            .join(PublishPost)
            .where(
                PublishPost.status == "done",
                PublishPost.completed_at <= now - timedelta(days=30),
                PublishMedia.deleted_at.is_(None),
            )
        ):
            remove_files(settings, media)
            media.deleted_at = now
            count += 1
    return count
