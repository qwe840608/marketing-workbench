"""Synthetic publication transport and media fixtures; never opens a provider socket."""

import json
import os
import re
import struct
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs

import httpx


def video_bytes(width=1080, height=1920, duration=12, version=0, rotated=False, padding=0):
    def atom(kind, data):
        return struct.pack(">I4s", len(data) + 8, kind) + data

    tkhd = bytearray(96 if version else 84)
    tkhd[0] = version
    offset, matrix = (88, 52) if version else (76, 40)
    tkhd[offset : offset + 8] = struct.pack(">II", width << 16, height << 16)
    if rotated:
        tkhd[matrix : matrix + 8] = struct.pack(">ii", 0, 65536)
    mdhd = bytearray(36 if version else 24)
    mdhd[0] = version
    offset = 20 if version else 12
    mdhd[offset : offset + (12 if version else 8)] = struct.pack(
        ">IQ" if version else ">II", 1000, int(duration * 1000)
    )
    hdlr = bytes(8) + b"vide" + bytes(12)
    trak = atom(b"tkhd", tkhd) + atom(b"mdia", atom(b"mdhd", mdhd) + atom(b"hdlr", hdlr))
    head = atom(b"ftyp", b"isom" + bytes(4) + b"isommp42") + atom(b"moov", atom(b"trak", trak))
    # padding：用格式正確的 mdat 墊大檔案，供多段上傳測試使用。
    return head + (atom(b"mdat", bytes(padding)) if padding else b"")


def jpeg_bytes(width=1080, height=1080):
    return b"\xff\xd8\xff\xc0" + struct.pack(">HBHH", 7, 8, height, width) + b"\xff\xd9"


class YouTubeMock:
    """Google resumable upload 與縮圖的假回應；單元測試與隔離瀏覽器驗收共用，不開任何連線。

    faults：依序消耗的分段故障（每次分段 PUT 取一個）："drop"＝伺服器收到但連線中斷、
    "503"＝暫時錯誤且未收到、"404"＝工作階段失效、"400"＝永久拒絕。
    """

    def __init__(self):
        self.sessions = {}
        self.calls = []
        self.faults = []
        self.start_error = None
        self.thumbnail_error = None
        # 模擬 YouTube 回報與請求不同的實際公開狀態（例如被限制為私人）。
        self.forced_privacy = None
        self.serial = 0
        self.completed = []

    def thumbnail_failure(self):
        """測試直接設 thumbnail_error；隔離瀏覽器驗收（另一個程序）改用資料庫旁的旗標檔。"""
        if self.thumbnail_error:
            return self.thumbnail_error
        flag = Path(os.environ.get("DATABASE_PATH", "")).parent / "youtube-thumbnail-error.json"
        return tuple(json.loads(flag.read_text(encoding="utf-8"))) if flag.is_file() else None

    @staticmethod
    def error(status, reason):
        return httpx.Response(
            status, json={"error": {"code": status, "errors": [{"reason": reason}]}}
        )

    def handle(self, request):
        path, params = request.url.path, dict(request.url.params)
        self.calls.append(
            (request.method, path, params, dict(request.headers), len(request.content))
        )
        assert request.headers["authorization"].startswith("Bearer ")
        if path == "/upload/youtube/v3/thumbnails/set":
            assert request.method == "POST" and params["videoId"]
            failure = self.thumbnail_failure()
            if failure:
                return self.error(*failure)
            return httpx.Response(200, json={"kind": "youtube#thumbnailSetResponse", "items": []})
        assert path == "/upload/youtube/v3/videos", path
        if request.method == "POST":
            assert params["uploadType"] == "resumable" and params["part"] == "snippet,status"
            if self.start_error:
                return self.error(*self.start_error)
            metadata = json.loads(request.content.decode("utf-8"))
            self.serial += 1
            identity = f"mockupload{self.serial}"
            self.sessions[identity] = {
                "metadata": metadata,
                "total": int(request.headers["x-upload-content-length"]),
                "mime": request.headers["x-upload-content-type"],
                "received": 0,
                "done": None,
            }
            return httpx.Response(
                200,
                headers={
                    "location": "https://www.googleapis.com/upload/youtube/v3/videos"
                    f"?uploadType=resumable&upload_id={identity}"
                },
            )
        assert request.method == "PUT", request.method
        session = self.sessions.get(params.get("upload_id"))
        if session is None:
            return self.error(404, "notFound")
        value = request.headers["content-range"]
        if value.startswith("bytes */"):
            assert int(value.split("/")[1]) == session["total"] and not request.content
            if session["done"]:
                return httpx.Response(201, json=session["done"])
            return self.incomplete(session)
        first, last, total = (int(v) for v in re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", value).groups())
        assert total == session["total"] and len(request.content) == last - first + 1
        # 真實協定：除最後一段外，分段大小須為 256 KiB 的整數倍。
        assert last + 1 == total or len(request.content) % (256 * 1024) == 0
        fault = self.faults.pop(0) if self.faults else None
        if fault == "503":
            return httpx.Response(503)
        if fault == "404":
            return self.error(404, "notFound")
        if fault == "400":
            return self.error(400, "mediaBodyRequired")
        assert first == session["received"], (first, session["received"])
        session["received"] = last + 1
        if fault == "drop":
            raise httpx.ReadError("isolated connection drop")
        if session["received"] == total:
            self.serial += 1
            session["done"] = {
                "kind": "youtube#video",
                "id": f"mockvideo{self.serial}",
                "snippet": session["metadata"]["snippet"],
                "status": {
                    **session["metadata"]["status"],
                    **({"privacyStatus": self.forced_privacy} if self.forced_privacy else {}),
                },
            }
            self.completed.append(session["done"])
            return httpx.Response(201, json=session["done"])
        return self.incomplete(session)

    @staticmethod
    def incomplete(session):
        received = session["received"]
        headers = {"range": f"bytes=0-{received - 1}"} if received else {}
        return httpx.Response(308, headers=headers)


def request_fields(request):
    """POST 的表單欄位（urlencoded 或 multipart 的文字欄位），供測試斷言實際送出的參數。"""
    if request.method != "POST" or "application/octet-stream" in request.headers.get("content-type", ""):
        return {}
    if "multipart/form-data" in request.headers.get("content-type", ""):
        found = re.findall(rb'name="([^"]+)"\r\n\r\n(.*?)\r\n--', request.content, re.S)
        return {name.decode(): value.decode(errors="replace") for name, value in found}
    return {k: v[0] for k, v in parse_qs(request.content.decode(errors="replace")).items()}


class TikTokMock:
    """TikTok 收件匣：init 回 publish_id 與上傳網址、PUT 分段、狀態查詢依序前進。"""

    def __init__(self):
        self.inits, self.chunks, self.statuses = [], [], []
        self.inbox_full = False
        # 每次查詢狀態依序回傳；用完後停在最後一個。
        self.states = ["PROCESSING_UPLOAD", "SEND_TO_USER_INBOX"]
        self.posted_ids = []
        # FAILED 時附的 fail_reason；unknown_ids 內的 publish_id 查詢時回錯誤（已被 TikTok 清除）。
        self.fail_reason = None
        self.unknown_ids = set()

    def handle(self, request):
        path = request.url.path
        if request.url.host == "open-upload.tiktokapis.com":
            assert request.method == "PUT" and path == "/upload/isolated"
            first, last, total = map(int, re.fullmatch(
                r"bytes (\d+)-(\d+)/(\d+)", request.headers["content-range"]).groups())
            assert len(request.content) == last - first + 1 == int(request.headers["content-length"])
            self.chunks.append((first, last, total))
            return httpx.Response(201 if last == total - 1 else 206)
        assert request.headers["authorization"] == "Bearer isolated-tiktok-access"
        body = json.loads(request.content)
        if path == "/v2/post/publish/inbox/video/init/":
            self.inits.append(body)
            if self.inbox_full:
                return httpx.Response(403, json={"error": {
                    "code": "spam_risk_too_many_pending_share", "message": "private"}})
            return httpx.Response(200, json={"data": {
                "publish_id": "v_inbox_file~v2." + str(len(self.inits)),
                "upload_url": "https://open-upload.tiktokapis.com/upload/isolated"},
                "error": {"code": "ok"}})
        assert path == "/v2/post/publish/status/fetch/", path
        self.statuses.append(body["publish_id"])
        if body["publish_id"] in self.unknown_ids:
            return httpx.Response(400, json={"error": {"code": "invalid_publish_id"}})
        state = self.states[min(len(self.statuses), len(self.states)) - 1]
        data = {"status": state, "publicaly_available_post_id": self.posted_ids}
        if state == "FAILED" and self.fail_reason:
            data["fail_reason"] = self.fail_reason
        return httpx.Response(200, json={"data": data, "error": {"code": "ok"}})


class PlatformMock:
    def __init__(self):
        self.calls = []
        # 每個請求的 (方法, 主機, 路徑, 表單欄位)；calls 維持原本的三元組格式。
        self.requests = []
        self.fail_threads = False
        self.fail_facebook = False
        self.poll_forever = False
        self.serial = 0
        self.uploads = []
        self.fb_video = None
        self.fb_chunks = []
        # FB 封面（/{video-id}/thumbnails）：fail_cover 為 Meta 錯誤碼時回錯誤（200＝缺權限）。
        self.covers = []
        self.fail_cover = None
        self.youtube = YouTubeMock()
        self.tiktok = TikTokMock()

    def handler(self, request):
        self.calls.append((request.method, request.url.host, request.url.path))
        if request.url.host in {"open.tiktokapis.com", "open-upload.tiktokapis.com"}:
            return self.tiktok.handle(request)
        if request.url.host == "www.googleapis.com":
            # YouTube 的二進位上傳不是表單，另由 YouTubeMock 處理。
            return self.youtube.handle(request)
        self.requests.append(
            (request.method, request.url.host, request.url.path, request_fields(request))
        )
        path, host = request.url.path, request.url.host
        if (
            self.fail_facebook
            and request.method == "POST"
            and host in {"graph.facebook.com", "graph-video.facebook.com"}
            and "/100/" in path
        ):
            return httpx.Response(
                429, json={"error": {"code": 4, "message": "private-platform-error"}}
            )
        if self.fail_threads and host == "graph.threads.net" and request.method == "POST":
            return httpx.Response(
                429,
                json={
                    "error": {
                        "code": 4,
                        "message": "private-platform-error isolated-publish-token /media/private-token",
                    }
                },
            )
        if request.method == "GET" and host == "graph.threads.net" and path.endswith("/me/threads"):
            # 瀏覽器檢查：由檔案決定 Threads 完整清單；延遲讓畫面能看到「檢查中…」。
            listing = Path(os.environ.get("DATABASE_PATH", "")).parent / "presence-threads.json"
            if listing.is_file():
                time.sleep(1)
                ids = json.loads(listing.read_text(encoding="utf-8"))
                return httpx.Response(200, json={"data": [{"id": value} for value in ids]})
        if request.method == "GET":
            fields = request.url.params.get("fields")
            if fields in {"status", "status_code"}:
                return httpx.Response(
                    200, json={fields: "IN_PROGRESS" if self.poll_forever else "FINISHED"}
                )
            return httpx.Response(
                200,
                json={
                    "permalink": "https://www.threads.net/@isolated/post/abc"
                    if host == "graph.threads.net"
                    else "https://www.instagram.com/p/isolated/"
                },
            )
        if host == "rupload.facebook.com":
            self.uploads.append((dict(request.headers), request.content))
            return httpx.Response(200, json={"success": True})
        if path.endswith(("/video_reels", "/video_stories")):
            if request_fields(request).get("upload_phase") == "start":
                self.serial += 1
                identity = str(9000 + self.serial)
                return httpx.Response(200, json={"video_id": identity,
                    "upload_url": "https://rupload.facebook.com/video-upload/v26.0/" + identity})
            return httpx.Response(200, json={"success": True})
        if host == "graph-video.facebook.com" and path.endswith("/videos"):
            # 粉專影片分段上傳：start 回第一段範圍，transfer 每次前進半個檔案，finish 回成功。
            fields = request_fields(request)
            phase = fields.get("upload_phase")
            if phase == "start":
                self.serial += 1
                self.fb_video = {"size": int(fields["file_size"]), "id": str(9000 + self.serial)}
                size = self.fb_video["size"]
                return httpx.Response(200, json={"upload_session_id": "7001",
                    "video_id": self.fb_video["id"], "start_offset": "0",
                    "end_offset": str(max(1, size // 2))})
            if phase == "transfer":
                size = self.fb_video["size"]
                begin = int(fields["start_offset"])
                chunk = re.search(rb'name="video_file_chunk"', request.content)
                assert chunk and fields["upload_session_id"] == "7001"
                end = min(size, begin + max(1, size // 2))
                self.fb_chunks.append((begin, end))
                return httpx.Response(200, json={"start_offset": str(end),
                    "end_offset": str(min(size, end + max(1, size // 2)))})
            assert phase == "finish" and fields["upload_session_id"] == "7001"
            return httpx.Response(200, json={"success": True})
        if host == "graph.facebook.com" and path.endswith("/thumbnails"):
            self.covers.append((path, request_fields(request), request.content))
            if self.fail_cover is not None:
                return httpx.Response(
                    403, json={"error": {"code": self.fail_cover, "message": "isolated"}}
                )
            return httpx.Response(200, json={"success": True})
        self.serial += 1
        if b"application/x-www-form-urlencoded" in request.headers.get("content-type", "").encode():
            body = parse_qs(request.content.decode())
            if path.endswith("/media_publish") or path.endswith("/threads_publish"):
                assert body.get("creation_id")
        return httpx.Response(200, json={"id": str(9000 + self.serial)})

    def client(self):
        return httpx.Client(
            transport=httpx.MockTransport(self.handler),
            follow_redirects=False,
            trust_env=False,
            timeout=5,
        )


def install_publish_mock():
    from app.services import publish_platforms

    mock = PlatformMock()
    publish_platforms.client_factory = mock.client
    from app.services.gateway_workers import Workers

    def no_meta(*args, **kwargs):
        raise httpx.ConnectError("isolated Meta transport")

    # Facebook／Instagram 的完整清單走 Workers.http；隔離環境一律視為無法連線。
    Workers.http = staticmethod(no_meta)
    # A caption controls a single failure in the isolated browser subprocess.
    original = mock.handler
    failed = set()

    def handler(request):
        key = request.content.decode(errors="replace") if request.method == "POST" else ""
        if (
            request.url.host == "graph.threads.net"
            and request.method == "POST"
            and b"partial-case" in request.content
            and key not in failed
        ):
            failed.add(key)
            mock.calls.append((request.method, request.url.host, request.url.path))
            return httpx.Response(429, json={"error": {"code": 4, "message": "private-error"}})
        return original(request)

    mock.handler = handler
    return mock


def seed_youtube(session, settings, brand_id, *, upload=True, channel="UC_isolated_channel"):
    """已連結的 YouTube 頻道（單一品牌）；upload=False 模擬上線前既有、尚無上傳範圍的連結。"""
    from app.models import Account, OAuthConnection
    from app.models.base import utc_now
    from app.services import oauth, youtube_oauth

    for name, value in {
        "YOUTUBE_CLIENT_ID": "isolated.apps.googleusercontent.com",
        "YOUTUBE_CLIENT_SECRET": "isolated-youtube-client-secret",
        "YOUTUBE_CHANNEL_ID": channel,
        "YOUTUBE_ACCESS_TOKEN": "isolated-youtube-access",
        "YOUTUBE_REFRESH_TOKEN": "isolated-youtube-refresh",
    }.items():
        oauth.put_secret(session, settings, name, value)
    session.flush()
    scopes = youtube_oauth.SCOPES if upload else youtube_oauth.READ_SCOPES
    session.add(
        OAuthConnection(
            platform="youtube",
            account_name="隔離 YouTube 頻道",
            granted_scopes=list(scopes),
            credential_digest=oauth.digest_credentials(session, settings, "youtube"),
            expires_at=utc_now() + timedelta(hours=6),
            checked_at=utc_now(),
            cache_json={},
        )
    )
    session.add(
        Account(
            brand_id=brand_id,
            platform="youtube",
            external_id=channel,
            name="隔離 YouTube 頻道",
            token_ref="",
            status="connected",
        )
    )


def seed_tiktok(session, settings, brand_id, *, upload=True, open_id="isolated-tiktok-open-id"):
    """已連結的 TikTok 帳號；access token 尚未過期，所以發佈時不會換發。"""
    from app.models import Account, OAuthConnection
    from app.models.base import utc_now
    from app.services import oauth, tiktok_oauth

    for name, value in {
        "TIKTOK_CLIENT_KEY": "isolated-tiktok-client-key",
        "TIKTOK_CLIENT_SECRET": "isolated-tiktok-client-secret",
        "TIKTOK_OPEN_ID": open_id,
        "TIKTOK_ACCESS_TOKEN": "isolated-tiktok-access",
        "TIKTOK_REFRESH_TOKEN": "isolated-tiktok-refresh",
    }.items():
        oauth.put_secret(session, settings, name, value)
    session.flush()
    scopes = [s for s in tiktok_oauth.SCOPES if upload or s != "video.upload"]
    session.add(
        OAuthConnection(
            platform="tiktok",
            account_name="隔離 TikTok 帳號",
            granted_scopes=scopes,
            credential_digest=oauth.digest_credentials(session, settings, "tiktok"),
            expires_at=utc_now() + timedelta(days=300),
            cache_json={"access_expires_at": (utc_now() + timedelta(hours=20)).isoformat()},
        )
    )
    session.add(
        Account(
            brand_id=brand_id,
            platform="tiktok",
            external_id=open_id,
            name="隔離 TikTok 帳號",
            token_ref="",
            status="connected",
        )
    )


def unseed_tiktok(session):
    """隔離瀏覽器驗收每輪開始時還原成「TikTok 尚未連結」；發佈目標須已先刪除。"""
    from sqlalchemy import delete

    from app.models import Account, OAuthConnection, PlatformCredential

    session.execute(delete(Account).where(Account.platform == "tiktok"))
    session.execute(delete(OAuthConnection).where(OAuthConnection.platform == "tiktok"))
    session.execute(
        delete(PlatformCredential).where(PlatformCredential.provider.like("TIKTOK_%"))
    )


def unseed_youtube(session):
    """隔離瀏覽器驗收每輪開始時還原成「YouTube 尚未連結」；發佈目標須已先刪除。"""
    from sqlalchemy import delete

    from app.models import Account, OAuthConnection, PlatformCredential

    session.execute(delete(Account).where(Account.platform == "youtube"))
    session.execute(delete(OAuthConnection).where(OAuthConnection.platform == "youtube"))
    session.execute(
        delete(PlatformCredential).where(PlatformCredential.provider.like("YOUTUBE_%"))
    )


def seed_connections(session, settings, brand_id):
    from app.models import Account, OAuthConnection
    from app.models.base import utc_now
    from app.services import oauth

    for name, value in {
        "META_PAGE_ID": "100",
        "META_IG_ACCOUNT_ID": "200",
        "THREADS_USER_ID": "300",
        "META_USER_ACCESS_TOKEN": "isolated-publish-user-token",
        "META_PAGE_ACCESS_TOKEN": "isolated-publish-token",
        "THREADS_ACCESS_TOKEN": "isolated-publish-threads-token",
    }.items():
        oauth.put_secret(session, settings, name, value)
    session.flush()
    for source, scopes in [("meta", oauth.META_SCOPES), ("threads", oauth.THREADS_SCOPES)]:
        session.add(
            OAuthConnection(
                platform=source,
                account_name="隔離帳號",
                ig_username="isolated_ig",
                granted_scopes=list(scopes),
                credential_digest=oauth.digest_credentials(session, settings, source),
                expires_at=utc_now() + timedelta(days=60),
                checked_at=utc_now(),
                cache_json={"granted": list(scopes), "verified": True},
            )
        )
    for platform, identity in [("facebook", "100"), ("instagram", "200"), ("threads", "300")]:
        session.add(
            Account(
                brand_id=brand_id,
                platform=platform,
                external_id=identity,
                name="隔離 " + platform,
                token_ref="",
            )
        )
