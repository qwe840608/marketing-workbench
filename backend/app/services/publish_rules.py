"""Shared limits, lossless Threads segmentation and platform notices."""

import re
import unicodedata
from copy import deepcopy

from app.services.caption_markdown import to_platform_text

MB = 1024 * 1024
GB = 1024 * MB
IG_PNG_WARNING = "Instagram 會自動把 PNG 轉成 JPEG，透明背景會變白底"
IG_COVER_PNG_WARNING = "Reels 封面會轉成 JPEG 送出，透明背景會變白底"
IG_COVER_RATIO_WARNING = "Reels 封面建議 9:16，其他比例會裁切中間；分享到動態時會再裁成 1:1"
FB_COVER_RATIO_WARNING = "Facebook 封面建議與影片同比例"
# 影片已成功後才另外套用封面；失敗不影響貼文，可在發佈紀錄重新套用。
FB_COVER_ERRORS = {
    "permission_missing": "缺少 pages_manage_engagement 權限，請重新連結 Meta 後再重新套用",
    "token_invalid": "授權無效，請重新連結 Meta 後再重新套用",
    "media_rejected": "Facebook 無法接受這張封面，請換一張 JPG／PNG",
    "rate_limited": "近期呼叫次數過多，請稍後再試",
    "timeout": "Facebook 回應逾時，請稍後再重新套用",
    "file_missing": "封面檔案已不存在，無法重新套用",
    "unknown": "Facebook 暫時無法套用封面，請稍後再試",
}
# 工作檯的媒體上限：上傳、規則檢查與 Agent get_publish_options 共用這一份。
IMAGE_BYTES = 8 * MB
VIDEO_BYTES = GB
IMAGE_MIMES = ["image/jpeg", "image/png"]
VIDEO_MIMES = ["video/mp4", "video/quicktime"]
RULES = {
    "facebook": {
        "story_seconds_min": 0,
        "story_seconds_max": 60,
        "story_count": 10,
        "caption": 63206,
        "carousel": 10,
        "video_seconds": 1200,
        "reels_seconds_min": 3,
        "reels_seconds_max": 90,
        "reels_ratio": [9, 16],
        # 影片／Reels 封面（POST /{video-id}/thumbnails）：Meta 上限 10 MB，工作檯圖片上限 8 MB。
        "cover_bytes": 8 * MB,
        "cover_mimes": ["image/jpeg", "image/png"],
        "description": "粉專文字、JPEG／PNG、2–10 張多圖與一般影片（最長 20 分鐘、1 GB）",
    },
    "instagram": {
        "story_seconds_min": 3,
        "story_seconds_max": 60,
        "story_count": 10,
        "caption": 2200,
        "hashtag": 30,
        "mentions": 20,
        "carousel": 10,
        "video_seconds": 900,
        # Reels 封面（cover_url）：官方只收 JPEG、8 MB 內，非 9:16 會裁切中間；PNG 送出前轉 JPEG。
        "cover_bytes": 8 * MB,
        "cover_mimes": ["image/jpeg", "image/png"],
        "description": (
            "JPEG 8 MB；比例 4:5–1.91:1；輪播 2–10 張；Reels 3–900 秒；Reels 封面 JPEG／PNG 8 MB 內"
        ),
    },
    "threads": {
        "caption": 500,
        "hashtag": 1,
        "caption_counting": "unicode_characters_emoji_utf8_bytes",
        "carousel": 20,
        "video_seconds": 300,
        "description": "500 字、最多一個主題標籤；JPEG／PNG；輪播 2–20 個；影片最長 300 秒",
    },
    "youtube": {
        # 只支援影片。標題以字元計、說明以 UTF-8 位元組計（API 的上限）。
        "title": 100,
        "caption": 5000,
        "caption_counting": "utf8_bytes",
        "video_seconds": 43200,
        "hashtag_effective": 15,
        "long_video_seconds": 900,
        "shorts_seconds": 180,
        # YouTube 說明：Shorts 自訂縮圖目前只能在電腦版 YouTube Studio 加入，API 文件未列支援。
        "shorts_thumbnail": False,
        "thumbnail_bytes": 2 * MB,
        "thumbnail_min_width": 640,
        "thumbnail_mimes": ["image/jpeg", "image/png"],
        "description": "只支援影片；標題 100 字、說明 5000 位元組；自訂縮圖 JPEG／PNG 2 MB 內",
    },
    "tiktok": {
        # 只送影片到收件匣（未審核應用程式不能直接發佈）；收件匣 API 不收文案，文案只供複製。
        # 長度上限：官方媒體傳輸指南寫 API 上傳最長 10 分鐘，帳號上限較短時由使用者在 App 裁剪；
        # 依帳號查上限的 creator_info 需要 video.publish 權限，第一版沒有申請。
        "caption": 2200,
        "video_seconds": 600,
        "side_min": 360,
        "side_max": 4096,
        "pending_inbox": 5,
        "inbox_only": True,
        "description": (
            "只支援影片，送到 TikTok 收件匣後在 App 內補文案並發佈；"
            "最長 10 分鐘，長寬 360–4096 px；24 小時內最多 5 支待處理"
        ),
    },
}
# 各平台媒體規格（比例、寬度、長度下限、Threads 主題標籤），check() 與 Agent
# get_publish_options 共用。獨立於 RULES，因為 RULES 原樣回給 /api/publish/options，
# 併入會改變該回應；YouTube 規則另見 RULES["youtube"]。
MEDIA_RULES = {
    "facebook": {
        "image_ratio": None,
        "image_width": None,
        "video_ratio": None,
        "video_width_max": None,
        "video_seconds_min": 0,
        "hashtag_length_max": None,
        "hashtag_forbidden_characters": [],
    },
    "instagram": {
        "image_ratio": [0.8, 1.91],
        "image_width": [320, 1440],
        "video_ratio": [0.01, 10],
        "video_width_max": 1920,
        "video_seconds_min": 3,
        "hashtag_length_max": None,
        "hashtag_forbidden_characters": [],
    },
    "threads": {
        "image_ratio": [0.1, 10],
        "image_width": None,
        "video_ratio": None,
        "video_width_max": 1920,
        "video_seconds_min": 0,
        "hashtag_length_max": 50,
        "hashtag_forbidden_characters": [".", "&"],
    },
}
ERRORS = {
    "token_invalid": "授權無效，請重新連結帳號",
    "permission_missing": "發佈權限不足，請重新連結帳號",
    "not_ready": "帳號尚未就緒，請檢查平台連線",
    "account_changed": "發佈帳號已變更，請重新確認",
    "media_rejected": "平台拒絕媒體，請檢查規格",
    "rate_limited": "平台暫時限制請求，請稍後重試",
    "timeout": "平台處理逾時，請先至平台確認是否已發佈",
    "interrupted": "發佈中斷，請先至平台確認是否已發佈",
    "unknown": "無法確認發佈結果，請先至平台確認",
    "cancelled": "上次的重試已取消，尚未重新送出",
    "quota_exceeded": "YouTube 今日上傳額度已用完，請明天再試",
    "metadata_rejected": "YouTube 拒絕標題或說明，請修改後重試",
    "rules_failed": "貼文內容不符合平台規則（例如格式與素材不符），已停止送出，請修正後重試",
    "inbox_full": "TikTok 收件匣 24 小時內已有 5 支待處理影片，請先在 App 處理或刪除後再重試",
    "posting_banned": "TikTok 目前不允許這個帳號發文，請到 TikTok App 確認帳號狀態",
    "platform_busy": "TikTok 暫時無法處理影片，請稍後重試",
    "posting_limited": "TikTok 24 小時內透過 API 發文的次數已達上限，請改從 App 上傳",
    "spam_risk": "TikTok 判定這次上傳有風險，官方建議不要重試，請改從 App 上傳",
}
# 縮圖在影片成功後才另外套用；失敗不影響影片，原因另外記在發佈目標的 detail。
THUMBNAIL_ERRORS = {
    "forbidden": "頻道尚未通過電話驗證，或沒有自訂縮圖的權限；請先在 YouTube 完成頻道驗證",
    "invalid_image": "YouTube 無法接受這張縮圖，請換一張 JPG／PNG",
    "rate_limited": "近期套用縮圖的次數過多，請稍後再試",
    "quota_exceeded": "YouTube 今日額度已用完，請明天再試",
    "token_invalid": "授權無效，請重新連結 YouTube 後再重新套用",
    "not_found": "找不到影片，可能已在 YouTube 刪除",
    "file_missing": "縮圖檔案已不存在，無法重新套用",
    "unknown": "YouTube 暫時無法套用縮圖，請稍後再試",
}


# hashtag 遇到空白或標點即結束，與平台判讀一致；避免把後面的句子當成 Threads 主題標籤。
HASHTAGS = re.compile(r"(?<!\w)#\w+")
MENTIONS = re.compile(r"(?<![\w@])@[\w.]+")
NAMES = {
    "facebook": "Facebook",
    "instagram": "Instagram",
    "threads": "Threads",
    "youtube": "YouTube",
    "tiktok": "TikTok",
}
DEFAULT_OPTIONS = {
    # cover_media_id（各平台）只由伺服端維護（上傳封面時綁定、移除時清除）。
    "facebook": {"video_format": "reels", "cover_media_id": None},
    # cover_media_id 只由伺服端維護（上傳封面時綁定、移除時清除）。
    "instagram": {"share_to_feed": True, "cover_media_id": None},
    "threads": {"segments": [], "segments_custom": False},
    # title 空白＝沿用 YouTube 說明（預設跟共用文案）的第一行；thumbnail_media_id 只由伺服端維護。
    "youtube": {
        "title": "",
        "privacy": "public",
        "made_for_kids": False,
        "thumbnail_media_id": None,
    },
    # TikTok 沒有可設定的選項（隱私、音樂、文案都在 App 內完成）；保留鍵讓既有迴圈一致。
    "tiktok": {},
}


def form_defaults():
    """給表單的預設選項：縮圖與封面編號由伺服端維護，不是可輸入的欄位，所以不放進預設值。"""
    options = deepcopy(DEFAULT_OPTIONS)
    options["youtube"].pop("thumbnail_media_id")
    options["instagram"].pop("cover_media_id")
    options["facebook"].pop("cover_media_id")
    return options


def platform_options(post):
    options = deepcopy(DEFAULT_OPTIONS)
    # 缺欄位值的舊模型維持 feed；新草稿在 save 明確設 reels。
    options["facebook"]["video_format"] = "feed"
    for platform, values in (getattr(post, "platform_options_json", None) or {}).items():
        options[platform].update(values)
    return options


def effective_options(post):
    # FB 草稿同樣支援 Reels（video_state=DRAFT），不再改成影片貼文。
    return platform_options(post)


# Unicode Emoji property (18.0), ranges from unicode.org/Public/UCD/latest/ucd/emoji/emoji-data.txt.
# 精確列出 Emoji，避免把數學符號或非 emoji 字元算成位元組。
EMOJI = re.compile(
    "["
    "\u0023\u002a\u0030-\u0039\u00a9\u00ae\u203c\u2049\u2122\u2139\u2194-\u2199"
    "\u21a9-\u21aa\u231a-\u231b\u2328\u23cf\u23e9-\u23f3\u23f8-\u23fa\u24c2"
    "\u25aa-\u25ab\u25b6\u25c0\u25fb-\u25fe\u2600-\u2604\u260e\u2611"
    "\u2614-\u2615\u2618\u261d\u2620\u2622-\u2623\u2626\u262a\u262e-\u262f"
    "\u2638-\u263a\u2640\u2642\u2648-\u2653\u265f-\u2660\u2663\u2665-\u2666"
    "\u2668\u267b\u267e-\u267f\u2692-\u2697\u2699\u269b-\u269c\u26a0-\u26a1"
    "\u26a7\u26aa-\u26ab\u26b0-\u26b1\u26bd-\u26be\u26c4-\u26c5\u26c8"
    "\u26ce-\u26cf\u26d1\u26d3-\u26d4\u26e9-\u26ea\u26f0-\u26f5\u26f7-\u26fa"
    "\u26fd\u2702\u2705\u2708-\u270d\u270f\u2712\u2714\u2716\u271d\u2721\u2728"
    "\u2733-\u2734\u2744\u2747\u274c\u274e\u2753-\u2755\u2757\u2763-\u2764"
    "\u2795-\u2797\u27a1\u27b0\u27bf\u2934-\u2935\u2b05-\u2b07\u2b1b-\u2b1c"
    "\u2b50\u2b55\u3030\u303d\u3297\u3299\U0001f004\U0001f0cf"
    "\U0001f170-\U0001f171\U0001f17e-\U0001f17f\U0001f18e\U0001f191-\U0001f19a"
    "\U0001f1e6-\U0001f1ff\U0001f201-\U0001f202\U0001f21a\U0001f22f"
    "\U0001f232-\U0001f23a\U0001f250-\U0001f251\U0001f300-\U0001f321"
    "\U0001f324-\U0001f393\U0001f396-\U0001f397\U0001f399-\U0001f39b"
    "\U0001f39e-\U0001f3f0\U0001f3f3-\U0001f3f5\U0001f3f7-\U0001f4fd"
    "\U0001f4ff-\U0001f53d\U0001f549-\U0001f54e\U0001f550-\U0001f567"
    "\U0001f56f-\U0001f570\U0001f573-\U0001f57a\U0001f587\U0001f58a-\U0001f58d"
    "\U0001f590\U0001f595-\U0001f596\U0001f5a4-\U0001f5a5\U0001f5a8"
    "\U0001f5b1-\U0001f5b2\U0001f5bc\U0001f5c2-\U0001f5c4\U0001f5d1-\U0001f5d3"
    "\U0001f5dc-\U0001f5de\U0001f5e1\U0001f5e3\U0001f5e8\U0001f5ef\U0001f5f3"
    "\U0001f5fa-\U0001f64f\U0001f680-\U0001f6c5\U0001f6cb-\U0001f6d2"
    "\U0001f6d5-\U0001f6d9\U0001f6dc-\U0001f6e5\U0001f6e9\U0001f6eb-\U0001f6ec"
    "\U0001f6f0\U0001f6f3-\U0001f6fc\U0001f7e0-\U0001f7eb\U0001f7f0"
    "\U0001f90c-\U0001f93a\U0001f93c-\U0001f945\U0001f947-\U0001f9ff"
    "\U0001fa70-\U0001fa7c\U0001fa80-\U0001fac6\U0001fac8\U0001facc-\U0001fadd"
    "\U0001fadf-\U0001faeb\U0001faef-\U0001fafa"
    "]"
)


def text_units(text):
    """Keep emoji sequences intact; count their UTF-8 bytes, other Unicode chars as one."""
    index = 0
    while index < len(text):
        start = index
        index += 1
        regional = 0x1F1E6 <= ord(text[start]) <= 0x1F1FF
        if regional and index < len(text) and 0x1F1E6 <= ord(text[index]) <= 0x1F1FF:
            index += 1
        while index < len(text):
            code = ord(text[index])
            if (
                unicodedata.combining(text[index])
                or code in (0xFE0E, 0xFE0F, 0x20E3)
                or 0x1F3FB <= code <= 0x1F3FF
                or 0xE0020 <= code <= 0xE007F
            ):
                index += 1
            elif code == 0x200D and index + 1 < len(text):
                index += 2
            else:
                break
        unit = text[start:index]
        emoji = EMOJI.search(unit) is not None
        yield unit, len(unit.encode("utf-8")) if emoji else len(unit)


def text_length(text, platform="threads"):
    return sum(size for _, size in text_units(text)) if platform == "threads" else len(text)


def overflow(text, limit, platform="threads"):
    """回傳 (第幾個字開始超出, 該處起的片段)；未超出回傳 None。

    字數依平台計法，位置以畫面上的字計。
    """
    used = 0
    units = list(text_units(text)) if platform == "threads" else [(c, 1) for c in text]
    for position, (_, size) in enumerate(units, 1):
        used += size
        if used > limit:
            return position, "".join(u for u, _ in units[position - 1 : position + 9])
    return None


def over_limit_reason(label, text, limit, platform="threads"):
    found = overflow(text, limit, platform)
    if not found:
        return None
    position, snippet = found
    return (
        f"{label}超過 {limit:,} 字上限：共 {text_length(text, platform):,} 字，"
        f"從第 {position:,} 個字「{snippet}」開始超出"
    )


def raw_caption(post, platform):
    """平台專用文案有內容才取代共用文案；空白覆寫（例如 Agent 存成 ""）沿用共用文案。"""
    value = post.captions_json.get(platform)
    return value if value and value.strip() else post.caption


def platform_caption(post, platform):
    """實際送出的文案：raw_caption 再把 Markdown 轉成平台顯示得出來的純文字。"""
    return to_platform_text(raw_caption(post, platform))


def threads_segments(post):
    options = platform_options(post)["threads"]
    if options["segments"] or options["segments_custom"]:
        segments = [to_platform_text(segment) for segment in options["segments"]]
        # 第一則就是 Threads 文案：舊草稿存成空白時改用實際文案，不送出空白貼文。
        if segments and not segments[0].strip():
            segments[0] = platform_caption(post, "threads")
        return segments
    return [platform_caption(post, "threads")]


def rules_view():
    return deepcopy(RULES)


def youtube_caption(post):
    return platform_caption(post, "youtube")


def youtube_title(options, caption):
    """標題空白時沿用說明的第一個非空行；回傳已去除前後空白的結果。"""
    title = (options.get("title") or "").strip()
    if title:
        return title
    for line in (caption or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def is_short(item):
    """直式或正方形且 3 分鐘內會被 YouTube 歸為 Shorts；API 無法指定。"""
    limit = RULES["youtube"]["shorts_seconds"]
    return bool(
        item.mime.startswith("video/")
        and item.width > 0
        and item.height >= item.width
        and item.duration
        and 0 < item.duration <= limit
    )


def check(
    platform, format, caption, media, options=None, *, unpublished=False, thumbnail=None, cover=None
):
    if format == "story":
        return check_story(platform, caption, media, options, unpublished=unpublished)
    if platform == "youtube":
        return check_youtube(format, caption, media, options, thumbnail)
    if platform == "tiktok":
        return check_tiktok(format, caption, media)
    rule = RULES[platform]
    limits = MEDIA_RULES[platform]
    reasons, warnings = [], []
    options = options or {}
    supported = not (platform == "instagram" and format == "text")
    if not supported:
        reasons.append("Instagram 不支援純文字")
    segments = options.get("segments") if platform == "threads" else None
    segments = [caption] if segments is None else segments
    if platform == "threads":
        if not segments:
            reasons.append("串文至少需要一段")
        for index, segment in enumerate(segments, 1):
            # Threads 文案是第一則，之後是各則回覆；超過上限只提示，不自動拆段。
            label = "Threads 文案" if index == 1 else f"回覆 {index - 1}"
            reason = over_limit_reason(label, segment, rule["caption"])
            if reason:
                reasons.append(reason)
            if not segment.strip() and (index > 1 or format == "text"):
                reasons.append(f"{label}不可空白")
        caption = "\n".join(segments)
    elif len(caption) > rule["caption"]:
        reasons.append(over_limit_reason("文案", caption, rule["caption"], platform))
    tags = HASHTAGS.findall(caption)
    if platform == "instagram" and len(tags) > rule["hashtag"]:
        reasons.append("hashtag 最多 30 個")
    if platform == "instagram" and len(MENTIONS.findall(caption)) > rule["mentions"]:
        reasons.append("@ 標註最多 20 個")
    if platform == "facebook" and MENTIONS.search(caption):
        warnings.append("Facebook 發文無法標註，@ 會顯示為一般文字")
    if platform == "threads" and len(tags) > 1:
        warnings.append("Threads 只用第一個 hashtag 當主題標籤，其餘顯示為一般文字")
    if platform == "threads" and tags:
        tag = tags[0][1:]
        if len(tag) > limits["hashtag_length_max"] or any(
            c in tag for c in limits["hashtag_forbidden_characters"]
        ):
            reasons.append("主題標籤最多 50 字，不能含句點或 &")
    if format == "text" and (media or not caption.strip()):
        reasons.append("純文字須有文案且不能包含媒體")
    if format in {"image", "video"} and len(media) != 1:
        reasons.append("此格式需 1 個媒體檔")
    if format == "carousel" and not 2 <= len(media) <= rule["carousel"]:
        reasons.append(f"輪播需 2–{rule['carousel']} 個媒體檔")
    for item in media:
        video = item.mime.startswith("video/")
        if (format == "video" and not video) or (format == "image" and video):
            reasons.append("媒體型別與格式不符")
        if format == "carousel" and platform != "threads" and video:
            reasons.append("本版輪播僅支援圖片")
        if video:
            if item.size > VIDEO_BYTES:
                reasons.append("影片最多 1 GB")
            reels = platform == "facebook" and options.get("video_format") == "reels"
            minimum = rule["reels_seconds_min"] if reels else limits["video_seconds_min"]
            maximum = rule["reels_seconds_max"] if reels else rule["video_seconds"]
            if reels and (
                item.width <= 0 or item.height <= 0 or abs(item.width / item.height - 9 / 16) > 0.01
            ):
                reasons.append("Facebook Reels 影片需為 9:16 直式")
            if not item.duration or not minimum < item.duration <= maximum:
                # IG 允許恰好 3 秒。
                if not ((platform == "instagram" or reels) and item.duration == 3):
                    reasons.append(f"影片長度需 {minimum}–{maximum} 秒")
            if limits["video_ratio"]:
                low, high = limits["video_ratio"]
                if not low <= item.width / item.height <= high:
                    reasons.append("Reels 影片比例需 0.01:1–10:1（建議 9:16）")
            if limits["video_width_max"] and item.width > limits["video_width_max"]:
                reasons.append("影片寬度最多 1920 px")
            if platform == "instagram" and format == "video" and cover is not None:
                reasons += check_cover(cover, warnings)
            if platform == "facebook" and format == "video" and cover is not None:
                reasons += check_facebook_cover(cover, item, warnings)
        else:
            if item.size > IMAGE_BYTES:
                reasons.append("圖片最多 8 MB")
            ratio = item.width / item.height
            if platform == "instagram":
                if item.mime == "image/png":
                    warnings.append(IG_PNG_WARNING)
                elif item.mime != "image/jpeg":
                    reasons.append("Instagram 圖片只支援 JPEG 或 PNG")
                low, high = limits["image_ratio"]
                if not low <= ratio <= high:
                    reasons.append("圖片比例需 4:5–1.91:1")
                narrow, wide = limits["image_width"]
                if not narrow <= item.width <= wide:
                    reasons.append("圖片寬度需 320–1440 px")
            if platform == "threads":
                low, high = limits["image_ratio"]
                if not low <= ratio <= high:
                    reasons.append("圖片比例需 0.1:1–10:1")
    reasons = list(dict.fromkeys(reasons))
    warnings = list(dict.fromkeys(warnings))
    return {
        "supported": supported,
        "ok": not reasons,
        "reasons": [NAMES[platform] + "：" + reason for reason in reasons],
        "warnings": warnings,
        "topic_tag": tags[0][1:] if platform == "threads" and tags else None,
    }


def check_cover(cover, warnings):
    """Instagram Reels 封面；比例不符只提示（平台裁切中間 9:16），格式與大小不符才擋。"""
    rule = RULES["instagram"]
    reasons = []
    if cover.mime not in rule["cover_mimes"]:
        reasons.append("封面只支援 JPG／PNG")
    if cover.size > rule["cover_bytes"]:
        reasons.append(f"封面最多 {rule['cover_bytes'] // MB} MB")
    if cover.mime == "image/png":
        warnings.append(IG_COVER_PNG_WARNING)
    if cover.height <= 0 or abs(cover.width / cover.height - 9 / 16) > 0.01:
        warnings.append(IG_COVER_RATIO_WARNING)
    return reasons


def check_facebook_cover(cover, video, warnings):
    """Facebook 影片／Reels 封面：只收 JPG／PNG、8 MB 內；比例與影片不同只提示。"""
    rule = RULES["facebook"]
    reasons = []
    if cover.mime not in rule["cover_mimes"]:
        reasons.append("封面只支援 JPG／PNG")
    if cover.size > rule["cover_bytes"]:
        reasons.append(f"封面最多 {rule['cover_bytes'] // MB} MB")
    if (
        cover.height <= 0
        or video.height <= 0
        or abs(cover.width / cover.height - video.width / video.height) > 0.02
    ):
        warnings.append(FB_COVER_RATIO_WARNING)
    return reasons


def check_youtube(format, caption, media, options, thumbnail):
    rule = RULES["youtube"]
    reasons, warnings = [], []
    options = options or {}
    supported = format == "video"
    if not supported:
        reasons.append("YouTube 只支援影片")
    else:
        if len(media) != 1:
            reasons.append("此格式需 1 個媒體檔")
        for item in media:
            if not item.mime.startswith("video/"):
                reasons.append("媒體型別與格式不符")
                continue
            if item.size > VIDEO_BYTES:
                reasons.append("影片最多 1 GB")
            if not item.duration or item.duration <= 0:
                reasons.append("無法讀取影片長度")
            elif item.duration > rule["video_seconds"]:
                reasons.append("影片最長 12 小時")
            elif item.duration > rule["long_video_seconds"]:
                warnings.append("超過 15 分鐘的影片需頻道已通過電話驗證")
    title = youtube_title(options, caption)
    if not title:
        reasons.append("標題必填")
    elif len(title) > rule["title"]:
        reasons.append(f"標題最多 {rule['title']} 字（目前 {len(title)}）")
    size = len(caption.encode("utf-8"))
    if size > rule["caption"]:
        reasons.append(f"說明最多 {rule['caption']:,} 位元組（目前 {size:,}）")
    if len(HASHTAGS.findall(caption)) > rule["hashtag_effective"]:
        warnings.append("說明超過 15 個 hashtag 時，YouTube 會忽略全部 hashtag")
    short = supported and len(media) == 1 and is_short(media[0])
    if short:
        warnings.append("將被歸為 Shorts（直式或正方形且 3 分鐘內，無法指定）")
    if thumbnail is not None and supported:
        if short and not rule["shorts_thumbnail"]:
            reasons.append("Shorts 不支援自訂縮圖，請移除縮圖")
        if thumbnail.mime not in rule["thumbnail_mimes"]:
            reasons.append("縮圖只支援 JPG／PNG")
        if thumbnail.size > rule["thumbnail_bytes"]:
            reasons.append(f"縮圖最多 {rule['thumbnail_bytes'] // MB} MB")
        if not short:
            if thumbnail.height <= 0 or abs(thumbnail.width / thumbnail.height - 16 / 9) > 0.02:
                warnings.append("縮圖建議 16:9（1280×720 以上）")
            elif thumbnail.width < rule["thumbnail_min_width"]:
                warnings.append(f"縮圖寬度建議至少 {rule['thumbnail_min_width']} px")
    reasons = list(dict.fromkeys(reasons))
    return {
        "supported": supported,
        "ok": not reasons,
        "reasons": [NAMES["youtube"] + "：" + reason for reason in reasons],
        "warnings": warnings,
        "topic_tag": None,
    }


TIKTOK_INBOX_NOTICE = "影片會送到 TikTok 收件匣，需要在 App 內補上文案並按發佈"
TIKTOK_IMAGE_REASON = "僅支援影片發布，圖文需從APP上傳"


def check_tiktok(format, caption, media):
    rule = RULES["tiktok"]
    reasons, warnings = [], [TIKTOK_INBOX_NOTICE]
    supported = format == "video"
    if not supported:
        reasons.append(TIKTOK_IMAGE_REASON)
    else:
        if len(media) != 1:
            reasons.append("此格式需 1 個媒體檔")
        for item in media:
            if not item.mime.startswith("video/"):
                reasons.append(TIKTOK_IMAGE_REASON)
                continue
            if item.size > VIDEO_BYTES:
                reasons.append("影片最多 1 GB")
            if not item.duration or item.duration <= 0:
                reasons.append("無法讀取影片長度")
            elif item.duration > rule["video_seconds"]:
                reasons.append("影片最長 10 分鐘")
            elif item.duration > 180:
                warnings.append("超過 3 分鐘：若帳號上限較短，需在 App 內裁剪")
            sides = (item.width, item.height)
            if not all(rule["side_min"] <= side <= rule["side_max"] for side in sides):
                reasons.append("影片長寬需 360–4096 px")
    if len(caption) > rule["caption"]:
        warnings.append(f"文案超過 {rule['caption']} 字，貼到 App 時可能被截斷")
    reasons = list(dict.fromkeys(reasons))
    return {
        "supported": supported,
        "ok": not reasons,
        "reasons": [NAMES["tiktok"] + "：" + reason for reason in reasons],
        "warnings": warnings,
        "topic_tag": None,
    }


def check_story(platform, caption, media, options=None, *, unpublished=False):
    reasons, warnings = [], []
    supported = platform in {"facebook", "instagram"}
    if not supported:
        reasons.append("限時動態僅支援 Facebook／Instagram")
    if caption or unpublished:
        reasons.append("限時動態不支援文字或存成 FB 草稿")
    if not 1 <= len(media) <= 10:
        reasons.append("限時動態需 1–10 則素材")
    for index, item in enumerate(media, 1):
        errors = []
        if item.mime.startswith("video/"):
            minimum = 3 if platform == "instagram" else 0
            if not item.duration or item.duration < minimum or item.duration > 60:
                errors.append("影片長度需 3–60 秒" if minimum else "影片最長 60 秒")
            if item.size > VIDEO_BYTES:
                errors.append("影片最多 1 GB")
            if platform == "instagram" and item.width > MEDIA_RULES["instagram"]["video_width_max"]:
                errors.append("影片寬度最多 1920 px")
        elif item.mime.startswith("image/"):
            if item.size > IMAGE_BYTES:
                errors.append("圖片最多 8 MB")
            if platform == "instagram" and item.mime == "image/png":
                warnings.append(f"第 {index} 則：{IG_PNG_WARNING}")
            elif platform == "instagram" and item.mime != "image/jpeg":
                errors.append("Instagram 圖片只支援 JPEG 或 PNG")
        else:
            errors.append("每則需一張圖片或一支影片")
        if item.height <= 0 or abs(item.width / item.height - 9 / 16) > 0.01:
            warnings.append(f"第 {index} 則非 9:16，平台會加邊")
        reasons.extend(f"第 {index} 則：{error}" for error in errors)
    return {
        "supported": supported,
        "ok": not reasons,
        "reasons": [NAMES[platform] + "：" + reason for reason in reasons],
        "warnings": warnings,
        "topic_tag": None,
    }
