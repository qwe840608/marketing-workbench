"""Agent entry points reuse publishing, with durable one use capabilities."""

import json
import secrets
import threading
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.models.agent_publish import AgentPublishConfirmation, AgentUpload
from app.models.base import utc_now
from app.schemas.publish import IdeaDraftInput, PostInput, PublishAction
from app.services import (
    agent_auth,
    agent_content,
    agent_queries,
    ideation,
    post_thumbnails,
    publish,
    publish_media,
)
from app.services.publish_rules import (
    IMAGE_BYTES,
    IMAGE_MIMES,
    MEDIA_RULES,
    RULES,
    VIDEO_BYTES,
    VIDEO_MIMES,
    effective_options,
    is_short,
    platform_caption,
    platform_options,
    raw_caption,
    threads_segments,
    youtube_caption,
    youtube_title,
)

# get_publish_post 附的素材預覽張數上限；輪播超過就只附前幾張，控制單次回應大小。
PREVIEW_LIMIT = 4
REPREPARE = "確認已失效；下一步：重新 prepare_publish，完整呈現明細並取得使用者明確同意"
INSTRUCTION = (
    "把明細完整呈現給使用者，取得使用者明確同意（例如『確認發佈』）後才呼叫 "
    "confirm_publish；不得自行假設同意。明細若被截斷，禁止確認，請縮短文案後重新準備。"
)


def public_targets(rows):
    for target in rows:
        target.pop("platform_post_id", None)
        if "permalink" in target:
            target["permalink"] = agent_queries.brand_url(target["permalink"])
        for story in target.get("stories", []):
            story.pop("platform_post_id", None)
            if "permalink" in story:
                story["permalink"] = agent_queries.brand_url(story["permalink"])
        target["detail"] = {
            key: value
            for key, value in target["detail"].items()
            if key
            in {
                "successful_segments",
                "total_segments",
                "failed_segment",
                "successful_stories",
                "total_stories",
                "failed_story",
                # YouTube：縮圖結果與實際公開狀態；影片編號與上傳工作階段不外露。
                "thumbnail",
                # Facebook：封面套用結果（status／code）。
                "cover",
                "privacy_status",
                # TikTok：收件匣進度，指南據此說明「已送到收件匣」；publish_id、貼文編號不外露。
                "inbox_state",
            }
        }
    return rows


# 佔位字串來自 MCP 投影的遮蔽與截斷；存進文案就會被當成原文發佈出去。
PLACEHOLDERS = ("[REDACTED_", "[觀眾帳號]", "[觀眾]", "[已遮蔽]", "[已截斷]")


def brand_fields(value):
    """標記品牌自撰的發佈欄位：MCP 投影只過濾秘密，不套觀眾個資遮蔽。"""
    if not isinstance(value, dict):
        return value
    value = dict(value)
    for key in ("caption", "captions", "platform_captions", "threads_segments"):
        if key in value:
            value[key] = agent_queries.brand(value[key])
    for key in ("platform_options", "effective_platform_options"):
        if isinstance(value.get(key), dict):
            options = {p: dict(o) if isinstance(o, dict) else o for p, o in value[key].items()}
            if isinstance(options.get("threads"), dict) and "segments" in options["threads"]:
                options["threads"]["segments"] = agent_queries.brand(options["threads"]["segments"])
            if isinstance(options.get("youtube"), dict) and "title" in options["youtube"]:
                options["youtube"]["title"] = agent_queries.brand(options["youtube"]["title"])
            value[key] = options
    if isinstance(value.get("youtube"), dict) and "title" in value["youtube"]:
        title = agent_queries.brand(value["youtube"]["title"])
        value["youtube"] = {**value["youtube"], "title": title}
    if isinstance(value.get("media"), list):
        value["media"] = [named(item) for item in value["media"]]
    for key in ("thumbnail", "cover", "facebook_cover"):
        if isinstance(value.get(key), dict):
            value[key] = named(value[key])
    return value


def named(item):
    if isinstance(item, dict) and "name" in item:
        return {**item, "name": agent_queries.brand(item["name"])}
    return item


def reject_placeholders(caption, captions=None, segments=None, title=None):
    texts = [caption or "", *(captions or {}).values(), *(segments or []), title or ""]
    if any(mark in text for text in texts for mark in PLACEHOLDERS):
        raise HTTPException(
            422,
            "文案含遮蔽佔位字串，請提供原文；下一步：向使用者取得原始文案，"
            "勿把查詢結果的遮蔽或截斷字串存回",
        )


def safe_post(access, settings, identity):
    post = publish.get(access, identity, include_drafts=True)
    value = brand_fields(publish.view(access.session, post))
    value["targets"] = public_targets(value["targets"])
    value["checks"] = publish.checks(access, settings, identity, include_drafts=True)
    return value


def preview_images(access, settings, identity):
    """發佈素材的圖片預覽（長邊 480px JPEG），讓 Agent 送出前看得到要發的圖。

    只取 role=media 的圖片，最多 PREVIEW_LIMIT 張；影片不附。單張讀不到或格式不符就略過，
    不讓預覽影響草稿內容的回傳。
    """
    post = publish.get(access, identity, include_drafts=True)
    images = []
    for media in publish.media_rows(access.session, post.id):
        if len(images) >= PREVIEW_LIMIT:
            break
        if media.mime not in IMAGE_MIMES or media.size > IMAGE_BYTES:
            continue
        try:
            content = publish_media.path_for(settings, media).read_bytes()
            data, _, _ = post_thumbnails.shrink(content)
        except (HTTPException, OSError, post_thumbnails.Unavailable):
            continue
        images.append(data)
    return images


def list_posts(access, body):
    rows = publish.listing(access, body.brand_id, include_drafts=True)
    if body.status:
        rows = [row for row in rows if row["status"] == body.status]
    for row in rows:
        row["targets"] = public_targets(row["targets"])
    items = [
        brand_fields({
            key: row[key]
            for key in (
                "id",
                "status",
                "format",
                "platforms",
                "scheduled_at",
                "facebook_unpublished",
                "platform_options",
                "effective_platform_options",
                "warnings",
                "report_id",
                "idea_index",
                "targets",
                "agent_source",
            )
        }
        | {"caption": row["caption"][:60], "media_count": len(row["media"])})
        for row in rows[body.offset : body.offset + body.limit]
    ]
    return {
        "items": items,
        "next_offset": body.offset + len(items) if len(rows) > body.offset + len(items) else None,
    }


def options(access, settings, body):
    return {
        **publish.options(access, settings, body.brand_id),
        "rules": {
            platform: youtube_rule(rule)
            if platform == "youtube"
            else tiktok_rule(rule)
            if platform == "tiktok"
            else {
                **rule,
                "hashtag": rule.get("hashtag"),
                "image_bytes": IMAGE_BYTES,
                "video_bytes": VIDEO_BYTES,
                "image_mimes": list(IMAGE_MIMES),
                "video_mimes": list(VIDEO_MIMES),
                "text_supported": platform != "instagram",
                "media_count": {
                    "text": 0,
                    "image": 1,
                    "video": 1,
                    "carousel": {"min": 2, "max": rule["carousel"]},
                    **({"story": {"min": 1, "max": 10}} if platform != "threads" else {}),
                },
                "carousel_types": ["image", "video"] if platform == "threads" else ["image"],
                **deepcopy(MEDIA_RULES[platform]),
            }
            for platform, rule in RULES.items()
        },
    }


def tiktok_rule(rule):
    """TikTok 只把一支影片送到收件匣；文案不會送出，由使用者在 App 內貼上。"""
    return {
        **rule,
        "hashtag": None,
        "video_bytes": VIDEO_BYTES,
        "video_mimes": list(VIDEO_MIMES),
        "text_supported": False,
        "media_count": {"video": 1},
        "caption_sent": False,
    }


def youtube_rule(rule):
    """YouTube 只有影片＋選填縮圖；規則與其他平台的欄位不同，另外投影。"""
    return {
        **rule,
        "hashtag": None,
        "video_bytes": VIDEO_BYTES,
        "video_mimes": list(VIDEO_MIMES),
        "text_supported": False,
        "media_count": {"video": 1},
        "thumbnail": {
            "mimes": rule["thumbnail_mimes"],
            "bytes": rule["thumbnail_bytes"],
            "min_width": rule["thumbnail_min_width"],
            "shorts_supported": rule["shorts_thumbnail"],
        },
    }


def safety(access, brand_id, caption, captions=None, segments=None, title=None):
    phrases = ideation.brand_context(access.session, brand_id)["forbidden_phrases"]
    agent_content.check_phrases(
        {
            "caption": caption,
            "platform_captions": captions or {},
            "segments": segments or [],
            "youtube_title": title or "",
        },
        phrases,
    )


def post_safety(access, post):
    safety(
        access,
        post.brand_id,
        post.caption,
        post.captions_json,
        threads_segments(post),
        platform_options(post)["youtube"]["title"],
    )


def draft(access, identity):
    post = publish.editable(access, identity)
    if post.status != "draft":
        raise HTTPException(
            409, "僅草稿可修改；下一步：排程中先 cancel_schedule，已送出不可修改或刪除"
        )
    return post


def record(session, post, grant, action, **detail):
    publish.audit(
        session, post, "agent." + action, f"staff:{grant.staff_id}", {"via": grant.name, **detail}
    )


def details(access, settings, post, selected, scheduled_at, retry):
    brand = access.require_brand(post.brand_id)
    accounts = publish.accounts(access.session, settings, post.brand_id)
    media = publish.media_rows(access.session, post.id)
    checked = publish.checks(access, settings, post.id)
    youtube = instagram = facebook = None
    cover = publish.cover_row(access.session, post)
    facebook_cover = publish.facebook_cover_row(access.session, post)
    if "instagram" in selected and post.format == "video":
        instagram = {"has_cover": cover is not None}
    if "facebook" in selected and post.format == "video":
        facebook = {"has_cover": facebook_cover is not None}
    if "youtube" in selected:
        options = platform_options(post)["youtube"]
        thumbnail = publish.thumbnail_row(access.session, post)
        youtube = {
            "title": youtube_title(options, youtube_caption(post)),
            "privacy": options["privacy"],
            "made_for_kids": bool(options["made_for_kids"]),
            "has_thumbnail": thumbnail is not None,
            "shorts": bool(media) and is_short(media[0]),
        }
    display = {
        "brand": brand.name,
        "post_id": post.id,
        "version": post.version,
        "format": post.format,
        "story_count": len(media) if post.format == "story" else None,
        "story_progress": [
            {"platform": t["platform"], **t["detail"]}
            for t in public_targets(publish.view(access.session, post)["targets"])
            if post.format == "story" and t["platform"] in selected
        ],
        "accounts": {p: accounts[p].name for p in selected},
        "caption": post.caption,
        "platform_captions": post.captions_json,
        # 只列出 Markdown 轉換後與原稿不同的平台（實際送出的文字），避免長文案在明細重複兩次。
        "sent_captions": {}
        if post.format == "story"
        else {
            p: text for p in selected if (text := platform_caption(post, p)) != raw_caption(post, p)
        },
        "platform_options": platform_options(post),
        "effective_platform_options": effective_options(post),
        "threads_segments": threads_segments(post),
        "warnings": list(dict.fromkeys(w for p in selected for w in checked[p]["warnings"])),
        "threads_progress": [
            t["detail"]
            for t in public_targets(publish.view(access.session, post)["targets"])
            if t["platform"] == "threads"
        ],
        # true：Facebook 存成草稿不發佈（Instagram／Threads 不受影響）。
        "facebook_unpublished": bool(post.facebook_unpublished) and "facebook" in selected,
        "media": publish.view(access.session, post)["media"],
        "scheduled_at": agent_queries.safe(scheduled_at),
        "timing": "排程" if scheduled_at else "立即發佈",
        "retry": retry,
        # 只在這次會送 YouTube 時出現：標題、公開狀態、兒童內容、是否有自訂縮圖。
        "youtube": youtube,
        # 只在這次會送 Instagram Reels 時出現：是否有自訂封面（沒有則用影片第一格）。
        "instagram": instagram,
        # 只在這次會送 Facebook 影片時出現：是否有自訂封面（影片成功後才另外套用）。
        "facebook": facebook,
        # TikTok 只送到收件匣，文案不會送出；確認前要讓使用者知道還要在 App 內發佈。
        "tiktok": {"delivery": "inbox", "caption_sent": False} if "tiktok" in selected else None,
    }
    # 品牌自撰欄位只過濾秘密；prepare 的「可完整呈現」檢查因此不會擋下品牌電話或 @帳號。
    # 標記不改變 JSON 序列化，指紋與原值相同。
    display = brand_fields(display)
    # Account identity and file digests are hashed, never included in MCP projections.
    fingerprint = {
        "display": display,
        "thumbnail": [thumbnail.id, thumbnail.sha256] if youtube and thumbnail else None,
        "cover": [cover.id, cover.sha256] if instagram and cover else None,
        "facebook_cover": [facebook_cover.id, facebook_cover.sha256]
        if facebook and facebook_cover
        else None,
        # 原始選項也進指紋：改了選項，舊確認碼一律失效。
        "facebook_unpublished": bool(post.facebook_unpublished),
        "platform_options": platform_options(post),
        "status": post.status,
        "target_progress": [t.detail_json for t in publish.targets(access.session, post.id)],
        "accounts": {p: [accounts[p].id, accounts[p].external_id] for p in selected},
        "media": [[m.id, m.sha256, m.position] for m in media],
    }
    return display, agent_auth.digest(
        json.dumps(fingerprint, sort_keys=True, ensure_ascii=False, default=str)
    )


def kickoff(factory, settings, post_id):
    threading.Thread(
        target=publish.execute, args=(factory, settings, post_id), daemon=True, name="agent-publish"
    ).start()


# confirm／retry／cancel 會對平台送出或撤回，與網頁的「送出發佈」同一個權限。
SUBMIT_TOOLS = {"confirm_publish", "retry_failed_platforms", "cancel_schedule"}


def tool_permission(name):
    return "publish.submit" if name in SUBMIT_TOOLS else "publish.edit"


def write(factory, settings, grant_id, name, body, origin=None):
    execute = False
    with factory() as session:
        access, grant = agent_content.access_for(
            session, grant_id, write=True, permission=tool_permission(name)
        )
        source = {"agent": grant.name, "grant_id": grant.id}
        if name == "save_publish_draft":
            access.require_brand(body.brand_id, write=True)
            post = draft(access, body.post_id) if body.post_id else None
            supplied_threads = body.platform_options.threads if body.platform_options else None
            segments = supplied_threads.segments if supplied_threads else None
            if segments is None and post:
                segments = threads_segments(post)
            supplied_youtube = body.platform_options.youtube if body.platform_options else None
            title = supplied_youtube.title if supplied_youtube else None
            reject_placeholders(body.caption, body.platform_captions, segments, title)
            if title is None and post:
                title = platform_options(post)["youtube"]["title"]
            safety(access, body.brand_id, body.caption, body.platform_captions, segments, title)
            # 省略選項時沿用草稿原值；平台已不含 Facebook 時選項自然失效，不讓它殘留。
            unpublished = body.facebook_unpublished
            if unpublished is None:
                unpublished = bool(post and post.facebook_unpublished)
                unpublished = unpublished and "facebook" in body.platforms
            result = publish.save(
                access,
                PostInput(
                    brand_id=body.brand_id,
                    format=body.format,
                    caption=body.caption,
                    captions=body.platform_captions,
                    platforms=body.platforms,
                    facebook_unpublished=unpublished,
                    platform_options=body.platform_options,
                    version=body.version or 1,
                    media_ids=body.media_ids
                    if body.media_ids is not None
                    else [m.id for m in publish.media_rows(session, post.id)]
                    if post
                    else [],
                ),
                body.post_id,
                agent_source=source,
            )
        elif name == "create_draft_from_idea":
            reject_placeholders(body.caption)
            report, _ = publish.idea_material(access, body.report_id, body.idea_index)
            safety(access, report.brand_id, body.caption)
            result = publish.from_idea(
                access,
                settings,
                IdeaDraftInput(report_id=body.report_id, idea_index=body.idea_index),
                caption=body.caption,
                agent_source=source,
            )
            result["message"] = (
                "已建立草稿"
                if result["created"]
                else "已有未發佈草稿；請使用既有草稿 id，未覆寫文案"
            )
        else:
            post = publish.get(access, body.post_id)
            if name != "confirm_publish":
                post_safety(access, post)
            if name == "create_upload_link":
                draft(access, post.id)
                if not origin:
                    raise HTTPException(409, "缺少請求來源；下一步：由 MCP 連線呼叫")
                token = secrets.token_urlsafe(32)
                filename = Path(body.filename.replace("\\", "/")).name
                filename = agent_auth.name_for(filename) or "media"
                row = AgentUpload(
                    token_hash=agent_auth.digest(token),
                    post_id=post.id,
                    grant_id=grant.id,
                    staff_id=grant.staff_id,
                    filename=filename,
                    role=body.role,
                    expires_at=utc_now() + timedelta(minutes=10),
                )
                session.add(row)
                session.flush()
                record(
                    session,
                    post,
                    grant,
                    "upload_link",
                    upload_id=row.id,
                    filename=filename,
                    role=body.role,
                )
                url = origin + "/api/agent/uploads/" + token
                result = {
                    "upload_url": url,
                    "expires_at": row.expires_at,
                    "instructions": "10 分鐘內一次性 PUT 上傳；使用 Windows 內建 "
                    'curl.exe -T "<本機檔案路徑>" "' + url + '"；成功後呼叫 '
                    "get_publish_post 確認媒體已加入。失效須重新 create_upload_link。",
                }
            elif name == "remove_publish_media":
                draft(access, post.id)
                record(session, post, grant, "remove_media", media_id=body.media_id)
                result = publish.remove_media(access, settings, post.id, body.media_id)
            elif name == "delete_publish_draft":
                draft(access, post.id)
                result = publish.cancel(access, post.id, delete=True, via=grant.name)
            elif name == "cancel_schedule":
                if post.status not in {"scheduled", "paused"}:
                    raise HTTPException(
                        409, "不是排程中的貼文；下一步：先 get_publish_post 確認狀態"
                    )
                result = publish.cancel(access, post.id, via=grant.name)
            elif name in {"prepare_publish", "retry_failed_platforms"}:
                retry = name == "retry_failed_platforms" or body.retry
                action = PublishAction(
                    confirmed=True,
                    version=body.version,
                    scheduled_at=getattr(body, "scheduled_at", None),
                )
                post, _, selected, _ = publish.validate_prepare(
                    access, settings, post.id, action, retry=retry
                )
                display, fingerprint = details(
                    access, settings, post, selected, action.scheduled_at, retry
                )
                # Confirmation never authorizes content that the bounded response cannot show.
                if (
                    agent_queries.safe(display, text_limit=55_000) != display
                    or len(json.dumps(display, ensure_ascii=False)) > 55_000
                ):
                    raise HTTPException(
                        422, "明細含需遮蔽或過長內容；下一步：修改草稿，確保可完整呈現後重新準備"
                    )
                token = secrets.token_urlsafe(32)
                row = AgentPublishConfirmation(
                    token_hash=agent_auth.digest(token),
                    post_id=post.id,
                    grant_id=grant.id,
                    staff_id=grant.staff_id,
                    post_version=post.version,
                    detail_hash=fingerprint,
                    scheduled_at=action.scheduled_at,
                    retry=retry,
                    expires_at=utc_now() + timedelta(minutes=10),
                )
                session.add(row)
                session.flush()
                record(session, post, grant, "prepare", confirmation_id=row.id)
                result = {
                    "details": display,
                    "confirmation_code": token,
                    "expires_at": row.expires_at,
                    "instructions": INSTRUCTION,
                }
            elif name == "confirm_publish":
                row = session.scalar(
                    select(AgentPublishConfirmation).where(
                        AgentPublishConfirmation.token_hash
                        == agent_auth.digest(body.confirmation_code)
                    )
                )
                if (
                    not row
                    or row.used_at
                    or row.expires_at <= utc_now()
                    or row.staff_id != grant.staff_id
                    or row.post_id != post.id
                    or row.post_version != post.version
                ):
                    raise HTTPException(409, REPREPARE)
                action = PublishAction(
                    confirmed=True, version=row.post_version, scheduled_at=row.scheduled_at
                )
                try:
                    post_safety(access, post)
                    _, _, selected, _ = publish.validate_prepare(
                        access, settings, post.id, action, retry=row.retry
                    )
                    _, fingerprint = details(
                        access, settings, post, selected, row.scheduled_at, row.retry
                    )
                    if fingerprint != row.detail_hash:
                        raise HTTPException(409, REPREPARE)
                except HTTPException as error:
                    raise HTTPException(error.status_code, REPREPARE) from None
                row.used_at = utc_now()
                record(session, post, grant, "confirm", confirmation_id=row.id)
                result = publish.prepare(
                    access, settings, post.id, action, retry=row.retry, via=grant.name
                )
                execute = result["status"] == "publishing"
                result["next_step"] = "使用 get_publish_post 查看各平台結果；已送出不可修改或刪除"
            else:
                raise HTTPException(422, "不支援此工具")
        session.commit()
    if execute:
        kickoff(factory, settings, body.post_id)
    if "targets" in result:
        result["targets"] = public_targets(result["targets"])
    if isinstance(result.get("post"), dict) and "targets" in result["post"]:
        result["post"]["targets"] = public_targets(result["post"]["targets"])
    # 回傳的貼文與 get_publish_post 同樣只過濾秘密；prepare 的 details 已在 details() 標記。
    result = brand_fields(result)
    if isinstance(result.get("post"), dict):
        result["post"] = brand_fields(result["post"])
    return result


async def upload(request, token):
    agent_auth.origin_for(request)
    factory = request.app.state.session_factory

    # 寫入交易在 threadpool 執行，等待 SQLite 鎖時不凍結事件迴圈（見 publish_media.upload）。
    def claim():
        with factory.begin() as session:
            row = session.scalar(
                select(AgentUpload).where(AgentUpload.token_hash == agent_auth.digest(token))
            )
            if not row or row.used_at or row.expires_at <= utc_now():
                raise HTTPException(410, "上傳連結已使用或過期；請重新取得上傳連結")
            access, grant = agent_content.access_for(
                session, row.grant_id, write=True, permission="publish.edit"
            )
            if grant.staff_id != row.staff_id:
                raise HTTPException(410, "上傳連結已失效")
            post = draft(access, row.post_id)
            post_safety(access, post)
            row.used_at = utc_now()
            record(
                session,
                post,
                grant,
                "upload",
                upload_id=row.id,
                filename=row.filename,
                result="開始",
            )
            return row.grant_id, row.post_id, row.filename, row.id, row.role

    grant_id, identity, filename, upload_id, role = await run_in_threadpool(claim)
    # Claim before reading bytes. Failed uploads consume the capability too.
    with factory() as session:

        def revalidate(session):
            session.expire_all()
            access, grant = agent_content.access_for(
                session, grant_id, write=True, permission="publish.edit"
            )
            post = draft(access, identity)
            post_safety(access, post)
            record(
                session,
                post,
                grant,
                "upload",
                upload_id=upload_id,
                filename=filename,
                result="成功",
            )
            return access

        def load():
            access, _ = agent_content.access_for(session, grant_id)
            return access, draft(access, identity)

        access, post = await run_in_threadpool(load)
        return await publish_media.upload(
            request, access, post, filename, revalidate=revalidate, role=role
        )
