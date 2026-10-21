"""匯出只讀取白名單業務欄位，不接觸原始事件或帳號憑證。"""

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from dotenv import dotenv_values
from pydantic import SecretStr
from sqlalchemy import select

from app.config import REPO_ROOT
from app.models import Account, Brand, Contact, Message, MetricSnapshot, Post, Thread
from app.services import settings_store

TAIPEI = ZoneInfo("Asia/Taipei")
STAGES = {
    "inquiry": "詢價",
    "quoted": "已報價",
    "booked": "已預約",
    "completed": "已完工",
    "follow_up": "回訪",
}
COLORS = {"red": "紅名單", "green": "綠名單", "black": "黑名單"}
STATES = {"pending": "待回覆", "in_progress": "處理中", "replied": "已回覆", "closed": "已結案"}
PLATFORMS = {"line": "LINE", "facebook": "Facebook", "instagram": "Instagram", "threads": "Threads"}
METRICS = {
    "views": "觀看",
    "reach": "觸及",
    "likes": "按讚",
    "comments": "留言",
    "shares": "分享",
    "saves": "收藏",
}


class ExportText:
    def __init__(self, settings, session=None):
        values = [
            v.get_secret_value() for v in settings.__dict__.values() if isinstance(v, SecretStr)
        ]
        values.extend(
            v
            for k, v in dotenv_values(REPO_ROOT / ".env").items()
            if v
            and any(
                word in k.upper()
                for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "ENCRYPTION_KEY")
            )
        )
        if session is not None:
            from app.models import AICredential, AIKeyVerification
            from app.services.ai_keys import decrypt

            for model in (AICredential, AIKeyVerification):
                for encrypted in session.scalars(select(model.encrypted_key)):
                    values.append(decrypt(encrypted, settings).get_secret_value())
            from app.services import credentials

            # 網頁設定的平台權杖存在 platform_credentials，不在 settings／.env。
            # PLAIN 的帳號／頁面 ID 與網址不算秘密，遮了會破壞貼文網址。
            for name in credentials.NAMES:
                if name not in credentials.PLAIN:
                    values.append(credentials.raw(credentials.resolve(name, settings, session)))
        self.secrets = sorted(set(filter(None, values)), key=len, reverse=True)

    def __call__(self, value):
        text = "" if value is None else str(value)
        for secret in self.secrets:
            text = text.replace(secret, "[憑證已遮蔽]")
        text = re.sub(
            r"(?i)\b(api[_ -]?key|access[_ -]?token|password|secret)\s*[:=]\s*[^\s,;]+",
            r"\1=[憑證已遮蔽]",
            text,
        )
        return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)


def segment(value, limit=64):
    original = str(value)
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", original).strip(" .")
    if not clean or clean.split(".")[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"{p}{n}" for p in ("COM", "LPT") for n in range(1, 10)),
    }:
        clean = "_" + clean
    if clean != original or len(clean) > limit:
        clean = clean[: limit - 9] + "-" + hashlib.sha256(original.encode()).hexdigest()[:8]
    return clean


def validate_root(path, settings, *, obsidian=False):
    path = Path(path)
    if not path.is_absolute() or path == Path(path.anchor):
        raise ValueError("必須使用完整且獨立的匯出資料夾")
    root = path.resolve()
    protected = [
        REPO_ROOT,
        *settings.protected_paths,
    ]
    # .runtime/ and data/ are git-ignored; data/ is the default home for local data,
    # so a dedicated subfolder there (e.g. data/export) is allowed.
    data_dir = (REPO_ROOT / "data").resolve()
    ignored = root.is_relative_to((REPO_ROOT / ".runtime").resolve()) or (
        root != data_dir and root.is_relative_to(data_dir)
    )
    if obsidian:
        ignored = ignored or root.is_relative_to((REPO_ROOT / "社群留言").resolve())
    if any(
        (root == p.resolve() or root.is_relative_to(p.resolve()))
        and not (p == REPO_ROOT and ignored)
        for p in protected
    ):
        raise ValueError("不能將匯出放入程式、資料庫、日誌或知識庫目錄")
    if root in {settings.database_path.parent.resolve(), settings.log_path.parent.resolve()}:
        raise ValueError("匯出必須使用獨立的資料夾")
    return root


def root_path(session, settings):
    row = settings_store.get(session, "export_root")
    return validate_root(row.value_json if row else settings.export_root, settings)


def destination(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or any(p in {"..", "."} or ":" in p for p in relative.parts):
        raise ValueError("匯出路徑不合法")
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("匯出路徑超出根目錄")
    if any(
        p.is_symlink() or p.is_junction()
        for p in (path, *path.parents)
        if p != root and p.is_relative_to(root)
    ):
        raise ValueError("匯出子目錄不能使用連結")
    return path


def atomic_write(root, relative, content):
    target = destination(root, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with NamedTemporaryFile(
            prefix=".mwb-", suffix=".tmp", dir=target.parent, delete=False
        ) as output:
            temp = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        destination(root, relative)
        os.replace(temp, target)
    finally:
        if temp and temp.exists():
            temp.unlink()
    return target


def instant(value):
    return value.astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M:%S") if value else "尚無資料"


def permalink(value, clean):
    try:
        parts = urlsplit(clean(value))
    except ValueError:
        return ""
    if (
        parts.scheme not in {"http", "https"}
        or not parts.netloc
        or parts.username
        or parts.password
    ):
        return ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


@dataclass
class Dataset:
    brands: dict
    accounts: dict
    contacts: dict
    posts: dict
    threads: dict
    messages: dict
    metrics: dict
    clean: ExportText

    def thread_data(self, thread):
        contact = self.contacts.get(thread.contact_id)
        account = self.accounts[thread.account_id]
        return {
            "id": thread.id,
            "external_id": self.clean(thread.external_id),
            "contact": self.clean(contact.display_name if contact else "未提供名稱"),
            "platform": account.platform,
            "account": self.clean(account.name),
            "stage": STAGES[thread.stage],
            "color": COLORS.get(thread.list_color, "未設定"),
            "status": STATES[thread.status],
            "kind": "公開留言",
            "booking_date": str(thread.booking_date) if thread.booking_date else "未設定",
            "booking_units": thread.booking_units,
            "messages": [self.message_data(m) for m in self.messages.get(thread.id, [])],
        }

    def message_data(self, message):
        contact = self.contacts.get(message.contact_id)
        attachments = [
            self.clean(a.get("type", "附件"))
            for a in message.attachments_json
            if isinstance(a, dict)
        ]
        return {
            "time": instant(message.sent_at),
            "edited": bool(message.edited_at),
            "direction": message.direction,
            "author": "品牌回覆"
            if message.direction == "out"
            else self.clean(contact.display_name if contact else "客人"),
            "text": self.clean(message.text) or "（無文字訊息）",
            "attachments": attachments,
            "source": "、".join(message.sources_json or []),
        }


def dataset(session, settings, brand_id=None):
    brands = list(session.scalars(select(Brand).where(Brand.id == brand_id if brand_id else True)))
    ids = [b.id for b in brands]
    accounts = list(session.scalars(select(Account).where(Account.brand_id.in_(ids))))
    account_ids = [a.id for a in accounts]
    contacts = list(session.scalars(select(Contact).where(Contact.brand_id.in_(ids))))
    posts = list(
        session.scalars(select(Post).where(Post.account_id.in_(account_ids)).order_by(Post.id))
    )
    threads = list(
        session.scalars(
            select(Thread)
            .where(Thread.account_id.in_(account_ids), Thread.kind == "comment_thread")
            .order_by(Thread.id)
        )
    )
    messages = {}
    for m in session.scalars(
        select(Message)
        .where(Message.thread_id.in_([t.id for t in threads]))
        .order_by(Message.sent_at, Message.id)
    ):
        messages.setdefault(m.thread_id, []).append(m)
    contact_ids = {m.contact_id for rows in messages.values() for m in rows} | {
        t.contact_id for t in threads
    }
    contacts = [c for c in contacts if c.id in contact_ids]
    metrics = {}
    for m in session.scalars(
        select(MetricSnapshot)
        .where(MetricSnapshot.post_id.in_([p.id for p in posts]))
        .order_by(MetricSnapshot.captured_at, MetricSnapshot.id)
    ):
        metrics[m.post_id] = m
    return Dataset(
        *({x.id: x for x in rows} for rows in (brands, accounts, contacts, posts, threads)),
        messages,
        metrics,
        ExportText(settings, session),
    )


def frontmatter(brand, platform, external_id, url, updated, clean):
    values = {
        "brand": clean(brand.slug),
        "platform": platform,
        "external_id": clean(external_id),
        "permalink": url or None,
        "updated_at": updated.isoformat(),
    }
    return (
        "---\n"
        + "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in values.items())
        + "\n---\n"
    )
