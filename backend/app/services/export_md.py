import hashlib
import html
import json
import logging
import threading
import time

from app.models.base import utc_now
from app.services.export_data import (
    METRICS,
    TAIPEI,
    atomic_write,
    dataset,
    destination,
    frontmatter,
    instant,
    permalink,
    root_path,
    segment,
)

logger = logging.getLogger("mwb.export")
MANIFEST = ".mwb-markdown.json"


def literal(value):
    return (
        html.escape(str(value), quote=False)
        .replace("\\", "\\\\")
        .replace("*", "\\*")
        .replace("_", "\\_")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def conversation(value):
    lines = [
        f"### {value['kind']} #{value['id']} · {literal(value['contact'])}",
        "",
        f"- 平台／帳號：{literal(value['platform'])}／{literal(value['account'])}",
        f"- 狀態：{value['status']}；成交階段：{value['stage']}；名單：{value['color']}",
        f"- 預約日期：{value['booking_date']}；數量：{value['booking_units'] or '未設定'}",
        "",
    ]
    for message in value["messages"]:
        lines.extend(
            [
                f"**{message['time']} · {literal(message['author'])}**"
                + ("（已編輯）" if message["edited"] else ""),
                "",
            ]
        )
        lines.extend("> " + literal(line) for line in message["text"].splitlines())
        if message["attachments"]:
            lines.extend(
                [
                    "",
                    "附件類型："
                    + "、".join(literal(a) for a in message["attachments"])
                    + "（內容請至原平台查看）",
                ]
            )
        lines.extend(["", "資料來源：" + literal(message["source"]), ""])
    if not value["messages"]:
        lines.extend(["尚無訊息。", ""])
    return "\n".join(lines)


def documents(data):
    result, used = {}, set()

    def add(path, text, identifier):
        if path.casefold() in used:
            path = path.removesuffix(".md") + f"--{identifier}.md"
        used.add(path.casefold())
        result[path] = text.encode("utf-8")

    for post in data.posts.values():
        account = data.accounts[post.account_id]
        brand = data.brands[account.brand_id]
        linked = [t for t in data.threads.values() if t.post_id == post.id]
        records = [post, brand, account, *linked]
        records.extend(m for t in linked for m in data.messages.get(t.id, []))
        records.extend(
            data.contacts[m.contact_id]
            for t in linked
            for m in data.messages.get(t.id, [])
            if m.contact_id in data.contacts
        )
        metric = data.metrics.get(post.id)
        if metric:
            records.append(metric)
        url = permalink(post.permalink, data.clean)
        lines = [
            frontmatter(
                brand,
                account.platform,
                post.external_id,
                url,
                max(r.updated_at for r in records),
                data.clean,
            ),
            f"# {literal(data.clean(brand.name))} · 貼文紀錄",
            "",
            "此檔由工作區自動產生，請在後台修改資料。時間皆為台北時間。",
            "",
            f"發佈時間：{instant(post.published_at)}",
            "",
            "原始連結：" + (literal(url) or "未提供"),
            "",
            "## 貼文內容",
            "",
        ]
        lines.extend(
            "> " + literal(line)
            for line in (data.clean(post.caption) or "（無文字內容）").splitlines()
        )
        lines.extend(["", "## 最新數據", "", "| 指標 | 數值 |", "| --- | --- |"])
        for key, label in METRICS.items():
            value = getattr(metric, key) if metric else None
            lines.append(f"| {label} | {value if value is not None else '尚無資料'} |")
        lines.extend(
            [
                "",
                f"快照時間：{instant(metric.captured_at) if metric else '尚無資料'}",
                "",
                "## 留言串",
                "",
            ]
        )
        lines.extend(conversation(data.thread_data(t)) for t in linked)
        if not linked:
            lines.append("尚無留言。")
        date = post.published_at.astimezone(TAIPEI).date()
        path = (
            f"{segment(data.clean(brand.slug))}/posts/{account.platform}/"
            f"{date}_{segment(data.clean(post.external_id))}.md"
        )
        add(path, "\n".join(lines) + "\n", post.id)
    for contact in data.contacts.values():
        brand = data.brands[contact.brand_id]
        linked = [
            t
            for t in data.threads.values()
            if t.contact_id == contact.id
            or any(m.contact_id == contact.id for m in data.messages.get(t.id, []))
        ]
        records = [
            contact,
            brand,
            *linked,
            *(data.accounts[t.account_id] for t in linked),
            *(m for t in linked for m in data.messages.get(t.id, [])),
        ]
        lines = [
            frontmatter(
                brand,
                contact.platform,
                contact.external_id,
                "",
                max(r.updated_at for r in records),
                data.clean,
            ),
            f"# {literal(data.clean(contact.display_name))} · 用戶紀錄",
            "",
            "此檔由工作區自動產生，請在後台修改資料。時間皆為台北時間。",
            "",
        ]
        lines.extend(conversation(data.thread_data(t)) for t in linked)
        if not linked:
            lines.append("尚無留言紀錄。")
        path = (
            f"{segment(data.clean(brand.slug))}/users/{contact.platform}/"
            f"{segment(data.clean(contact.external_id))}_"
            f"{segment(data.clean(contact.display_name), 32)}.md"
        )
        add(path, "\n".join(lines) + "\n", contact.id)
    return result


class ExportWorker:
    """單一後端程序的匯出排程；重啟透過內容摘要補回尚未完成的工作。"""

    def __init__(self, factory, settings, *, debounce=20, interval=3):
        self.factory, self.settings = factory, settings
        self.debounce, self.interval = debounce, interval
        self.lock, self.stop_event = threading.Lock(), threading.Event()
        self.thread = None
        self.root, self.manifest, self.pending = None, {}, {}
        self.state = {"last_success_at": None, "error": None, "files": 0, "pending": 0}

    manifest_name = MANIFEST

    def document_source(self, session):
        return root_path(session, self.settings), documents(dataset(session, self.settings))

    def start(self):
        self.thread = threading.Thread(target=self.run, name="markdown-export", daemon=True)
        self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join()

    def run(self):
        while not self.stop_event.is_set():
            self.tick()
            self.stop_event.wait(self.interval)

    def status(self):
        return {
            **self.state,
            "enabled": self.settings.export_worker_enabled,
            "debounce_seconds": self.debounce,
        }

    def tick(self, *, force=False, now=None):
        with self.lock:
            try:
                return self._tick(force, time.monotonic() if now is None else now)
            except Exception as error:
                self.state = {**self.state, "error": "匯出失敗，請檢查磁碟與資料夾權限"}
                from app.logging_config import error_fields

                logger.error("markdown_export_failed", extra=error_fields(error))
                return {**self.status(), "ok": False}

    def _tick(self, force, now):
        with self.factory() as session:
            root, files = self.document_source(session)
        if root != self.root:
            force = force or self.root is not None
            self.root, self.manifest, self.pending = root, {}, {}
            manifest_path = destination(root, self.manifest_name)
            if manifest_path.is_file():
                saved = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.manifest = saved["files"]
                self.state["last_success_at"] = saved.get("updated_at")
        hashes = {p: hashlib.sha256(content).hexdigest() for p, content in files.items()}
        changed = {
            p
            for p, digest in hashes.items()
            if self.manifest.get(p) != digest or not destination(root, p).is_file()
        }
        removed = set(self.manifest) - set(files)
        for p in changed | removed:
            self.pending.setdefault(p, now)
        self.pending = {p: at for p, at in self.pending.items() if p in changed | removed}
        due = {p for p, at in self.pending.items() if force or now - at >= self.debounce}
        if not due:
            self.state = {
                **self.state,
                "error": None,
                "files": len(self.manifest),
                "pending": len(self.pending),
            }
            return {**self.status(), "ok": True, "written": 0}
        updated = dict(self.manifest)
        for p in due & changed:
            atomic_write(root, p, files[p])
            updated[p] = hashes[p]
        for p in due & removed:
            path = destination(root, p)
            # 只清除本引擎產生且未被人改寫的舊檔，保留使用者自行放入的檔案。
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == self.manifest[p]:
                path.unlink()
            updated.pop(p, None)
        at = utc_now().isoformat()
        atomic_write(
            root,
            self.manifest_name,
            json.dumps({"files": updated, "updated_at": at}, ensure_ascii=False).encode(),
        )
        self.manifest = updated
        for p in due:
            self.pending.pop(p, None)
        self.state = {
            "last_success_at": at,
            "error": None,
            "files": len(updated),
            "pending": len(self.pending),
        }
        return {**self.status(), "ok": True, "written": len(due & changed)}
