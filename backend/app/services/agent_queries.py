"""Explicit projections for MCP: no exports, raw payloads or member records."""

import re
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import (
    Account,
    Classification,
    Contact,
    Message,
    MetricSnapshot,
    Post,
    PostThumbnail,
    Thread,
)
from app.models.base import utc_now
from app.models.ideation import IdeationReport, VideoScript
from app.schemas.ideation import ScriptContent
from app.services import dashboard, ideation, ideation_settings, posts, video_scripts
from app.services.redact import redact

TAIPEI = ZoneInfo("Asia/Taipei")
SECRET = (
    # OpenAI／Anthropic 金鑰在 sk- 之後都遠超過 20 碼；短字串（例如品牌名 SK-II）不是秘密。
    r"\b(?:mwb_[A-Za-z0-9_-]{43}|sk-[A-Za-z0-9_-]{20,})\b"
    r"|(?i:bearer\s+)[A-Za-z0-9._-]+"
    r"|(?i:(?:token|password|secret|api_key)\s*[:=]\s*)[^\s,;]+"
)
SECRETS = re.compile(SECRET)
PRIVATE = re.compile(
    r"(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]|/(?:Users|home|tmp|var)/|\bdata[\\/])[^\s\"<>]*|"
    + SECRET
)
METRICS = (
    "captured_at",
    "views",
    "reach",
    "comments",
    "likes",
    "shares",
    "saves",
    "avg_watch_time",
    "completion_rate",
)


TEXT_LIMIT = 8_000
CUT = " [已截斷]"


def safe_text(value, *, text_limit=TEXT_LIMIT):
    # redact() grows superlinearly on long strings; no single field needs more than this,
    # and responses are bounded to MAX_TEXT anyway.
    if len(value) > text_limit:
        value = value[:text_limit] + CUT
    value = PRIVATE.sub("[已遮蔽]", redact(value).text)
    return re.sub(r"(?<!\w)@[\w.-]+", "[觀眾帳號]", value)


class BrandText(str):
    """品牌自撰、將公開發佈的文字（文案、分段、標題、素材名）。

    這是品牌自己要公開的內容，不是觀眾個資：電話、Email、@帳號、地址與網址都是原文；
    套觀眾遮蔽會讓 prepare 永遠失敗，Agent 回寫時還會把佔位字串存進文案。只過濾秘密。
    """


def safe_brand_text(value, *, text_limit=TEXT_LIMIT):
    if len(value) > text_limit:
        value = value[:text_limit] + CUT
    return SECRETS.sub("[已遮蔽]", str(value))


def brand(value):
    """遞迴標記品牌自撰文字；回傳新物件，不改動 ORM 的 JSON 欄位。"""
    if isinstance(value, str):
        return BrandText(value)
    if isinstance(value, dict):
        return {key: brand(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [brand(item) for item in value]
    return value


def safe(value, *, text_limit=TEXT_LIMIT):
    if isinstance(value, BrandText):
        return safe_brand_text(value, text_limit=text_limit)
    if isinstance(value, str):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})", value):
            try:
                return datetime.fromisoformat(value).astimezone(TAIPEI).isoformat()
            except ValueError:
                pass
        return safe_text(value, text_limit=text_limit)
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "astimezone"):
        return value.astimezone(TAIPEI).isoformat()
    if isinstance(value, dict):
        return {key: safe(item, text_limit=text_limit) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe(item, text_limit=text_limit) for item in value]
    return value


def window(body, days=None):
    until = body.until or utc_now()
    since = body.since or (until - timedelta(days=days) if days else None)
    if since is not None and since >= until:
        raise HTTPException(422, "期間起點須早於終點；下一步：調整 since 與 until")
    return since, until


def page(rows, body, project):
    items = [project(row) for row in rows[: body.limit]]
    return {
        "items": items,
        "next_offset": body.offset + body.limit if len(rows) > body.limit else None,
    }


def brand_guide(access, body):
    brand = access.require_brand(body.brand_id)
    context = ideation.brand_context(access.session, brand.id)
    return {
        "brand_id": brand.id,
        "name": brand.name,
        "shared_description": context["base_prompt"],
        "brand_description": context["brand_rules"],
        "forbidden_phrases": context["forbidden_phrases"],
        "topics": ideation_settings.config(access.session, brand.id).topics,
        "script_rules": {
            "schema": ScriptContent.model_json_schema(),
            "rules": [
                "片長 5–300 秒；1–20 鏡，每鏡 1–120 秒。",
                "鏡號從 1 連續，分鏡秒數加總等於片長；存回會正規化鏡號、機位與加總。",
                "包含 POV／側拍、ASMR、B-roll、授權；拍攝備註註明品牌資料待品牌覆核。",
                "保留品牌固定結尾；資訊不足先請使用者確認，不捏造價格或承諾。",
            ],
        },
    }


def get_dashboard(access, body):
    return {
        "summary": dashboard.summary(access, body.brand_id),
        "trends": dashboard.trends(access, body.brand_id, body.days),
    }


def metric(row):
    result = {field: getattr(row, field) for field in METRICS if hasattr(row, field)}
    # Threads 的轉發與引用存在 extra_json；FB／IG 沒有這兩項就不輸出。
    extra = row.extra_json if isinstance(getattr(row, "extra_json", None), dict) else {}
    result.update({
        key: extra[key] for key in ("reposts", "quotes", "watch_hours", "subscribers_gained")
        if type(extra.get(key)) in {int, float}
    })
    return result


def brand_url(url):
    """品牌自己的貼文網址；Threads 網址含品牌 @帳號，套觀眾遮蔽會變成壞連結。"""
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.username or parts.password:
        return None
    return BrandText(url)


def get_post_row(access, post_id):
    row = access.session.scalar(access.statement(Post).where(Post.id == post_id))
    if row is None:
        raise HTTPException(404, "找不到資料")
    return row


def post_view(access, row, *, detail=False):
    snapshots = list(
        access.session.scalars(
            select(MetricSnapshot)
            .where(MetricSnapshot.post_id == row.id)
            .order_by(MetricSnapshot.captured_at.desc(), MetricSnapshot.id.desc())
            .limit(30 if detail else 1)
        )
    )
    thumbnail = row.thumbnail
    result = {
        "id": row.id,
        "platform": access.session.get(Account, row.account_id).platform,
        "published_at": row.published_at,
        # 分析貼文要看完整文案；觀眾個資照樣遮蔽，長度交給回應上限處理。
        "caption": safe_text(row.caption or ""),
        "url": brand_url(row.permalink),
        "media_type": row.media_type,
        "has_image": bool(thumbnail and thumbnail.status == "ready" and thumbnail.digest),
        "latest_metrics": metric(snapshots[0]) if snapshots else None,
    }
    if detail:
        result["snapshots"] = [metric(item) for item in snapshots]
    return result


def post_image(access, post_id):
    """get_post 附上工作檯存的縮圖（長邊 480px JPEG），讓 Agent 看得到貼文圖片。"""
    row = get_post_row(access, post_id)
    image = access.session.scalar(
        select(PostThumbnail).where(
            PostThumbnail.post_id == row.id, PostThumbnail.status == "ready"
        )
    )
    if image is None or not image.data:
        return None
    return image.mime or "image/jpeg", image.data


def list_posts(access, body):
    access.require_brand(body.brand_id)
    # Keep the web service's brand and platform semantics, then apply exact ISO bounds.
    since, until = window(body)
    rows = posts.list_posts(
        access, body.brand_id, body.limit + 1, body.offset, body.platform, since=since, until=until
    )
    return page(rows, body, lambda row: post_view(access, row))


def comment_statement(access, body, days):
    access.require_brand(body.brand_id)
    since, until = window(body, days)
    query = access.statement(Message, body.brand_id).where(
        Thread.kind == "comment_thread",
        Message.direction == "in",
        Message.author_type == "fan",
        Message.sent_at >= since,
        Message.sent_at < until,
    )
    if getattr(body, "post_id", None):
        row = get_post_row(access, body.post_id)
        if access.session.get(Account, row.account_id).brand_id != body.brand_id:
            raise HTTPException(404, "找不到資料")
        query = query.where(Thread.post_id == row.id)
    latest = (
        select(Classification.intent)
        .where(Classification.message_id == Message.id)
        .order_by(Classification.id.desc())
        .limit(1)
        .correlate(Message)
        .scalar_subquery()
    )
    return (
        query.add_columns(
            Thread.post_id,
            func.coalesce(Message.contact_id, Thread.contact_id),
            latest.label("intent"),
        ),
        since,
        until,
    )


def boundary(name):
    # 英數名稱要求前後不是英數（Joe 不換 Joey）；中文句子沒有分詞空白，
    # 中文邊界若也套 \w 會讓句中的名字永遠不被替換，所以只在英數邊緣檢查。
    ascii_word = "[A-Za-z0-9_]"
    head = rf"(?<!{ascii_word})" if re.match(ascii_word, name[0]) else ""
    tail = rf"(?!{ascii_word})" if re.match(ascii_word, name[-1]) else ""
    return head + re.escape(name) + tail


def audience_text(session, text, contact_id):
    value = safe_text(text or "")
    contact = session.get(Contact, contact_id) if contact_id else None
    if contact:
        for identity in (contact.display_name, contact.external_id):
            name = redact(identity).text if identity else ""
            # 一兩個字的名稱（小美、Jo）會誤換無關文字（小美好），只換三字以上的名稱。
            if len(name) >= 3:
                value = re.sub(boundary(name), "[觀眾]", value)
    return value


def list_comments(access, body):
    query, since, until = comment_statement(access, body, 90)
    rows = access.session.execute(
        query.order_by(Message.sent_at.desc(), Message.id.desc())
        .offset(body.offset)
        .limit(body.limit + 1)
    ).all()
    identities = {}

    def project(row):
        message, post_id, contact_id, intent = row
        # No contact means no reliable identity: do not pretend all anonymous fans are one person.
        identity = contact_id if contact_id else ("unknown", message.id)
        if identity not in identities:
            number = len(identities)
            identities[identity] = "觀眾" + (chr(65 + number) if number < 26 else str(number + 1))
        return {
            "id": message.id,
            "post_id": post_id,
            "sent_at": message.sent_at,
            "text": audience_text(access.session, message.text, contact_id),
            "author": identities[identity],
            "intent": intent,
        }

    return {**page(rows, body, project), "since": since, "until": until}


def popular_questions(access, body):
    query, since, until = comment_statement(access, body, 30)
    groups = {}
    for message, _, contact_id, intent in access.session.execute(
        query.order_by(Message.sent_at.desc(), Message.id.desc())
    ):
        intent = intent or "unclassified"
        group = groups.setdefault(intent, {"intent": intent, "count": 0, "examples": []})
        group["count"] += 1
        if len(group["examples"]) < 3:
            group["examples"].append(
                {"id": message.id, "text": audience_text(access.session, message.text, contact_id)}
            )
    return {
        "items": sorted(groups.values(), key=lambda group: (-group["count"], group["intent"])),
        "next_offset": None,
        "since": since,
        "until": until,
    }


def exclusions_view(data):
    from app.schemas.agent_content import EXCLUSION_REASONS

    agent = data.get("agent_exclusions") or []
    return {
        "by_user": len(data.get("excluded_message_ids") or []) - len(agent),
        "by_agent": [{**item, "reason_label": EXCLUSION_REASONS.get(item["reason"], item["reason"])}
                     for item in agent],
    }


def report_view(access, row):
    data = row.data_json
    scripts = list(
        access.session.scalars(
            select(VideoScript)
            .where(VideoScript.report_id == row.id)
            .order_by(VideoScript.id.desc())
        )
    )
    return {
        "id": row.id,
        "brand_id": row.brand_id,
        "status": row.status,
        "error": row.error,
        "start_at": row.start_at,
        "end_at": row.end_at,
        "created_at": row.created_at,
        "comment_start": data.get("comment_start"),
        "comment_end": data.get("comment_end"),
        "source": data.get("source"),
        "provider": row.provider,
        "exclusions": exclusions_view(data),
        "version": data.get("ideas_revision", 1),
        "ideas": [
            {
                **{
                    k: idea.get(k)
                    for k in (
                        "topic",
                        "title",
                        "goal",
                        "hook",
                        "angle",
                        "keyword",
                        "element",
                        "visual",
                        "quote_ids",
                    )
                },
                "index": index,
                "version": data.get("ideas_revision", 1),
                "edited": bool(idea.get("edited")),
                "source": data.get("source"),
                "script_ids": [script.id for script in scripts if script.topic_index == index],
            }
            for index, idea in enumerate(data.get("ideas", []))
        ],
    }


def list_reports(access, body):
    access.require_brand(body.brand_id)
    rows = list(
        access.session.scalars(
            select(IdeationReport)
            .where(IdeationReport.brand_id == body.brand_id, IdeationReport.status != "deleted")
            .order_by(IdeationReport.id.desc())
            .offset(body.offset)
            .limit(body.limit + 1)
        )
    )
    return page(rows, body, lambda row: report_view(access, row))


def get_script(access, body):
    row = video_scripts.get(access, body.script_id)
    return {
        "id": row.id,
        "report_id": row.report_id,
        "topic_index": row.topic_index,
        "version": row.version,
        "content": row.content_json,
        "review": {k: row.review_json.get(k) for k in ("passed", "reasons", "notice")},
        "source": {"agent": row.model} if row.provider == "agent" else {"provider": row.provider},
    }
