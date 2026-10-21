"""Bounded header parsing and streaming capability downloads; no external tools."""

import hashlib
import io
import os
import re
import secrets
import struct
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException
from PIL import Image, ImageCms, UnidentifiedImageError
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from app.db import ensure_write
from app.models import PublishLink, PublishMedia
from app.models.base import utc_now
from app.services.publish_rules import IMAGE_BYTES, RULES, VIDEO_BYTES

TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
THUMBNAIL_BYTES = RULES["youtube"]["thumbnail_bytes"]
# 綁定到單一平台選項的圖片：用途 → (平台, 選項鍵, 位元組上限, 名稱)。
BOUND_ROLES = {
    "thumbnail": ("youtube", "thumbnail_media_id", THUMBNAIL_BYTES, "縮圖"),
    "cover": ("instagram", "cover_media_id", RULES["instagram"]["cover_bytes"], "封面"),
    "fb_cover": ("facebook", "cover_media_id", RULES["facebook"]["cover_bytes"], "封面"),
}
JPEG_SUFFIX = ".jpg"
JPEG_LIMIT = IMAGE_BYTES  # Instagram image_url 的 JPEG 上限與工作檯圖片上限相同
JPEG_QUALITIES = (90, 85, 80, 70, 60)


def path_for(settings, media):
    root = settings.publish_media_root.resolve()
    path = (root / media.relative_path).resolve()
    if path.parent != root or path.is_symlink():
        raise HTTPException(404, "Not Found")
    return path


def jpeg_path(settings, media):
    """PNG 轉成 Instagram 用 JPEG 的衍生檔；與原檔同目錄、檔名加後綴，隨原檔一起清除。"""
    path = path_for(settings, media)
    return path.with_name(path.name + ".ig.jpg")


def remove_files(settings, media):
    path_for(settings, media).unlink(missing_ok=True)
    jpeg_path(settings, media).unlink(missing_ok=True)


def encode_jpeg(image):
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        image = image.convert("RGBA")
        base = Image.new("RGB", image.size, (255, 255, 255))
        base.paste(image, mask=image.getchannel("A"))
        image = base
    elif image.mode not in {"RGB", "L"}:
        if image.mode.startswith("I"):
            image = image.point(lambda value: value / 256).convert("L")
        image = image.convert("RGB")
    profile = image.info.get("icc_profile")
    if profile and image.mode == "RGB":
        try:
            image = ImageCms.profileToProfile(
                image, ImageCms.ImageCmsProfile(io.BytesIO(profile)), ImageCms.createProfile("sRGB")
            )
        except (ImageCms.PyCMSError, OSError):
            pass
    if image.mode != "RGB":
        image = image.convert("RGB")
    for quality in JPEG_QUALITIES:
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=quality, optimize=True)
        if buffer.tell() <= JPEG_LIMIT:
            return buffer.getvalue()
    raise HTTPException(422, "圖片轉成 JPEG 後仍超過 8 MB")


def ensure_jpeg(settings, media):
    """為 PNG 產生（並沿用）JPEG 衍生檔：透明合成白底、sRGB、品質 90、保留尺寸。"""
    target = jpeg_path(settings, media)
    if target.is_file():
        return target
    try:
        with Image.open(path_for(settings, media)) as image:
            image.load()
            data = encode_jpeg(image)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(422, "圖片無法轉成 JPEG") from None
    temp = target.with_name(target.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        temp.write_bytes(data)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return target


def atoms(file, start, end):
    while start + 8 <= end:
        file.seek(start)
        size, kind = struct.unpack(">I4s", file.read(8))
        header = 8
        if size == 1:
            raw = file.read(8)
            if len(raw) != 8:
                raise ValueError("atom")
            size = struct.unpack(">Q", raw)[0]
            header = 16
        if size == 0:
            size = end - start
        if size < header or start + size > end:
            raise ValueError("atom")
        yield kind, start + header, start + size
        start += size


def metadata(path):
    with path.open("rb") as file:
        head = file.read(32)
        if head.startswith(b"\x89PNG\r\n\x1a\n") and head[12:16] == b"IHDR":
            width, height = struct.unpack(">II", head[16:24])
            result = "image/png", width, height, None
        elif head.startswith(b"\xff\xd8\xff"):
            file.seek(2)
            result = None
            while file.tell() < min(path.stat().st_size, 1024 * 1024):
                if file.read(1) != b"\xff":
                    raise ValueError("jpeg")
                marker = file.read(1)
                while marker == b"\xff":
                    marker = file.read(1)
                if marker in (b"\xd9", b"\xda", b""):
                    break
                length = struct.unpack(">H", file.read(2))[0]
                if length < 2:
                    raise ValueError("jpeg")
                if marker[0] in (0xC0, 0xC1, 0xC2):
                    _, height, width = struct.unpack(">BHH", file.read(5))
                    result = "image/jpeg", width, height, None
                    break
                file.seek(length - 2, 1)
            if result is None:
                raise ValueError("jpeg")
        elif head[4:8] == b"ftyp" and head[8:12] in {
            b"isom",
            b"iso2",
            b"mp41",
            b"mp42",
            b"avc1",
            b"M4V ",
            b"qt  ",
        }:
            result = None
            for kind, start, end in atoms(file, 0, path.stat().st_size):
                if kind != b"moov":
                    continue
                for child, a, b in atoms(file, start, end):
                    if child != b"trak":
                        continue
                    width = height = duration = None
                    video = False
                    for field, x, y in atoms(file, a, b):
                        if field == b"tkhd":
                            file.seek(x)
                            data = file.read(min(y - x, 128))
                            offset = 88 if data[0] == 1 else 76
                            width, height = (
                                v >> 16 for v in struct.unpack(">II", data[offset : offset + 8])
                            )
                            # tkhd matrix may rotate the display by 90 degrees.
                            matrix = 52 if data[0] == 1 else 40
                            aa, bb = struct.unpack(">ii", data[matrix : matrix + 8])
                            if aa == 0 and abs(bb) == 65536:
                                width, height = height, width
                        if field == b"mdia":
                            for field2, u, v in atoms(file, x, y):
                                file.seek(u)
                                data = file.read(min(v - u, 40))
                                if field2 == b"hdlr":
                                    video = data[8:12] == b"vide"
                                if field2 == b"mdhd":
                                    offset = 20 if data[0] == 1 else 12
                                    scale = struct.unpack(">I", data[offset : offset + 4])[0]
                                    seconds = struct.unpack(
                                        ">Q" if data[0] == 1 else ">I",
                                        data[offset + 4 : offset + (12 if data[0] == 1 else 8)],
                                    )[0]
                                    duration = seconds / scale if scale else None
                    if video and width and height and duration:
                        result = (
                            "video/quicktime" if head[8:12] == b"qt  " else "video/mp4",
                            width,
                            height,
                            duration,
                        )
                        break
            if result is None:
                raise ValueError("video")
        else:
            raise ValueError("type")
    if not 0 < result[1] <= 65536 or not 0 < result[2] <= 65536:
        raise ValueError("dimensions")
    return result


async def upload(request, access, post, filename, *, revalidate=None, role="media"):
    from app.services.publish import editable, instagram_sent, media_rows, targets, view

    if role not in {"media", *BOUND_ROLES}:
        raise HTTPException(422, "不支援的媒體用途")
    # thumbnail／cover 都是每篇一張、綁在平台選項上的圖片，不算發佈素材。
    thumbnail = role in BOUND_ROLES
    platform, option_key, bound_bytes, noun = BOUND_ROLES.get(role, (None, None, 0, ""))
    settings, session = request.app.state.settings, access.session

    # 資料庫步驟都交給 threadpool：取得 SQLite 寫入鎖可能等上 busy_timeout 加重試十幾秒，
    # 在事件迴圈上等會凍結整個伺服器；持鎖請求的 session 收尾也排不到事件迴圈而互相卡住。
    def claim():
        ensure_write(session)
        editable(access, post.id)
        session.commit()

    await run_in_threadpool(claim)
    root = settings.publish_media_root
    root.mkdir(parents=True, exist_ok=True)
    path = root / secrets.token_hex(24)
    size, digest = 0, hashlib.sha256()
    header, checked, image = b"", False, False
    try:
        with path.open("xb") as file:
            async for chunk in request.stream():
                size += len(chunk)
                if size > VIDEO_BYTES:
                    raise HTTPException(413, "單檔最多 1 GB")
                if len(header) < 16:
                    header = (header + chunk[:16])[:16]
                if not checked and len(header) == 16:
                    if not (
                        header.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff"))
                        or header[4:8] == b"ftyp"
                    ):
                        raise HTTPException(422, "僅接受有效 MP4／MOV／JPEG／PNG 媒體")
                    image = header.startswith((b"\x89PNG", b"\xff\xd8\xff"))
                    if thumbnail and not image:
                        raise HTTPException(422, f"{noun}僅接受 JPEG／PNG")
                    checked = True
                if image and size > IMAGE_BYTES:
                    raise HTTPException(413, "圖片最多 8 MB")
                if thumbnail and size > bound_bytes:
                    raise HTTPException(413, f"{noun}最多 {bound_bytes // 1024**2} MB")
                file.write(chunk)
                digest.update(chunk)

        def store(access, identity):
            try:
                mime, width, height, duration = metadata(path)
            except (ValueError, IndexError, struct.error):
                raise HTTPException(422, "僅接受有效 MP4／MOV／JPEG／PNG 媒體") from None
            ensure_write(session)
            if revalidate:
                access = revalidate(session)
            post = editable(access, identity)
            if post.format == "story" and any(
                t.detail_json.get("stories") for t in targets(session, post.id)
            ):
                raise HTTPException(409, "限時動態已部分發佈，不可新增素材")
            rows = media_rows(session, post.id)
            limit = 10 if post.format == "story" else 20
            if thumbnail:
                if post.format != "video":
                    raise HTTPException(422, f"{noun}僅適用於影片貼文")
                if not mime.startswith("image/"):
                    raise HTTPException(422, f"{noun}僅接受 JPEG／PNG")
                if role == "cover" and instagram_sent(session, post):
                    raise HTTPException(409, "Instagram 已發佈，不可變更封面")
            elif len(rows) >= limit:
                raise HTTPException(422, f"最多 {limit} 個媒體檔")
            if mime.startswith("image/") and size > IMAGE_BYTES:
                raise HTTPException(413, "圖片最多 8 MB")
            name = Path(filename.replace("\\", "/")).name[:255]
            name = "".join(c for c in name if ord(c) >= 32) or "media"
            replaced = []
            if thumbnail:
                # 每支影片只有一張縮圖／封面：新的取代舊的，舊檔在交易提交後才刪。
                for old in session.scalars(
                    select(PublishMedia).where(
                        PublishMedia.post_id == post.id,
                        PublishMedia.role == role,
                        PublishMedia.deleted_at.is_(None),
                    )
                ):
                    old.deleted_at = utc_now()
                    replaced.append(old)
            item = PublishMedia(
                post_id=post.id,
                position=0 if thumbnail else len(rows),
                original_name=name,
                relative_path=path.name,
                mime=mime,
                size=size,
                width=width,
                height=height,
                duration=duration,
                sha256=digest.hexdigest(),
                uploader_id=access.staff.id,
                role=role,
            )
            session.add(item)
            if thumbnail:
                session.flush()
                options = deepcopy(post.platform_options_json or {})
                options[platform] = {**options.get(platform, {}), option_key: item.id}
                post.platform_options_json = options
            post.updated_at = utc_now()
            session.commit()
            for old in replaced:
                remove_files(settings, old)
            return view(session, post)

        return await run_in_threadpool(store, access, post.id)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def create_link(session, settings, media, *, jpeg=False):
    """jpeg=True 且素材是 PNG 時，連結網址加 .jpg，下載時改送 JPEG 衍生檔（Instagram 用）。"""
    convert = jpeg and media.mime == "image/png"
    if convert:
        ensure_jpeg(settings, media)
    parts = urlsplit(settings.webhook_public_url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise HTTPException(409, "未設定公開媒體來源")
    token = secrets.token_urlsafe(32)
    link = PublishLink(
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        media_id=media.id,
        expires_at=utc_now() + timedelta(minutes=15),
    )
    session.add(link)
    session.flush()
    suffix = JPEG_SUFFIX if convert else ""
    return link.id, f"{parts.scheme}://{parts.netloc}/media/{token}{suffix}"


def download(factory, settings, token, range_header=None):
    converted = token.endswith(JPEG_SUFFIX)
    if converted:
        token = token[: -len(JPEG_SUFFIX)]
    if not TOKEN.fullmatch(token):
        raise HTTPException(404, "Not Found")
    with factory.begin() as session:
        link = session.scalar(
            select(PublishLink).where(
                PublishLink.token_hash == hashlib.sha256(token.encode()).hexdigest()
            )
        )
        now = utc_now()
        if not link or link.revoked_at or link.expires_at <= now or link.uses >= link.max_uses:
            raise HTTPException(404, "Not Found")
        media = session.get(PublishMedia, link.media_id)
        if not media or media.deleted_at:
            raise HTTPException(404, "Not Found")
        if converted and media.mime != "image/png":
            raise HTTPException(404, "Not Found")
        path = jpeg_path(settings, media) if converted else path_for(settings, media)
        try:
            file = path.open("rb")
            total = os.fstat(file.fileno()).st_size if converted else media.size
        except OSError:
            raise HTTPException(404, "Not Found") from None
        start, end, status = 0, total - 1, 200
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
            try:
                if not match or not any(match.groups()):
                    raise ValueError()
                first, last = match.groups()
                if first:
                    start, end = int(first), min(int(last), end) if last else end
                else:
                    suffix = int(last)
                    if suffix <= 0:
                        raise ValueError()
                    start = max(0, total - suffix)
                if start > end or start >= total:
                    raise ValueError()
            except ValueError:
                file.close()
                raise HTTPException(
                    416, "Range Not Satisfiable", headers={"Content-Range": f"bytes */{total}"}
                ) from None
            status = 206
        # 平台下載大型影片可能分成多個 Range 請求；只把「從頭開始」的請求算一次下載，
        # 避免分段續傳耗盡次數上限。連結仍受 15 分鐘到期與發佈後撤銷限制。
        if start == 0:
            link.uses += 1
        headers = {
            "Content-Length": str(end - start + 1),
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        }
        if status == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{total}"
        mime = "image/jpeg" if converted else media.mime

    def chunks():
        try:
            file.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = file.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk
        finally:
            file.close()

    return StreamingResponse(chunks(), status_code=status, media_type=mime, headers=headers)
