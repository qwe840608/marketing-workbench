"""Publish persisted public comments as content-addressed Obsidian notes."""

import json
from collections import defaultdict

from app.db import ensure_write
from app.models import AuditLog
from app.services import settings_store
from app.services.export_data import (
    METRICS,
    PLATFORMS,
    TAIPEI,
    dataset,
    instant,
    permalink,
    segment,
    validate_root,
)
from app.services.export_md import ExportWorker, literal

KEY = "obsidian_root"


def root_path(session, settings):
    row = settings_store.get(session, KEY)
    return validate_root(row.value_json if row else settings.obsidian_root, settings, obsidian=True)


def sync(access, worker):
    """管理員手動同步 Obsidian；只記成功與否，不記路徑或內容。"""
    result = worker.tick(force=True)
    # 同步可能很久，期間別的連線已提交；沿用請求的讀取快照升級寫入會遇到
    # SQLITE_BUSY_SNAPSHOT 而 503 並遺失稽核，先換成新的寫入交易。
    ensure_write(access.session)
    access.session.add(
        AuditLog(
            actor=f"staff:{access.staff.id}",
            action="obsidian.sync",
            target_type="workspace",
            detail_json={"ok": result["ok"]},
        )
    )
    access.session.commit()
    return result


def yaml(values):
    return (
        "---\n"
        + "\n".join(
            f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in values.items()
        )
        + "\n---\n\n"
    )


def documents(data):
    files = {}
    for post in data.posts.values():
        account = data.accounts[post.account_id]
        if account.platform not in {"facebook", "instagram"}:
            continue
        brand = data.brands[account.brand_id]
        records = sorted(
            (
                m
                for t in data.threads.values()
                if t.post_id == post.id
                for m in data.messages.get(t.id, [])
            ),
            key=lambda m: (m.sent_at, m.id),
        )
        date = (post.published_at or post.created_at).astimezone(TAIPEI).strftime("%Y-%m-%d")
        # A stable database ID also disambiguates case-insensitive and sanitized names.
        folder = (
            f"{segment(data.clean(brand.slug))}/{PLATFORMS[account.platform]}/"
            f"{date} {segment(data.clean(post.caption)[:20] or '無文字貼文', 48)}--{post.id}"
        )
        months = defaultdict(list)
        by_external = {m.external_id: m for m in records}
        for message in records:
            months[message.sent_at.astimezone(TAIPEI).strftime("%Y-%m")].append(message)
        for month, messages in sorted(months.items()):
            lines = [
                yaml({"post": data.clean(post.external_id), "month": month, "count": len(messages)})
            ]
            children = defaultdict(list)
            roots = []
            for message in messages:
                parent = by_external.get(message.comment_parent_id)
                if parent and parent in messages and parent.id != message.id:
                    children[parent.id].append(message)
                else:
                    roots.append(message)
            visited = set()

            def render(message, depth=0, visited=visited, lines=lines, children=children):
                if message.id in visited:
                    return
                visited.add(message.id)
                value = data.message_data(message)
                prefix = "> " * min(depth, 12)
                lines.append(
                    prefix + f"**{value['time']} · {literal(value['author'])}** ^留言-{message.id}"
                )
                if depth == 0 and message.comment_parent_id:
                    lines.append(f"> 回覆留言：{literal(data.clean(message.comment_parent_id))}")
                lines.extend(prefix + literal(line) for line in value["text"].splitlines())
                lines.append(prefix.rstrip())
                for child in children[message.id]:
                    render(child, depth + 1)

            for message in [*roots, *messages]:
                render(message)
            files[f"{folder}/留言 {month}.md"] = ("\n".join(lines) + "\n").encode("utf-8")
        metric = data.metrics.get(post.id)
        updated = max(
            [
                post.updated_at,
                *(m.updated_at for m in records),
                *([metric.captured_at] if metric else []),
            ]
        )
        text = (
            yaml(
                {
                    "platform": account.platform,
                    "external_id": data.clean(post.external_id),
                    "permalink": permalink(post.permalink, data.clean) or None,
                    "published_at": post.published_at.isoformat() if post.published_at else None,
                    "updated_at": updated.isoformat(),
                    "comment_count": len(records),
                }
            )
            + literal(data.clean(post.caption))
            + "\n\n"
        )
        if metric:
            metric_values = {field: getattr(metric, field) for field in METRICS}
            text += f"數據更新：{instant(metric.captured_at)}\n\n"
            text += (
                " · ".join(
                    f"{label}："
                    + str(metric_values[field] if metric_values[field] is not None else "尚無資料")
                    for field, label in METRICS.items()
                )
                + "\n\n"
            )
        text += "\n".join(f"[[留言 {month}]]" for month in sorted(months)) + "\n"
        files[f"{folder}/貼文.md"] = text.encode("utf-8")
    return files


class ObsidianWorker(ExportWorker):
    manifest_name = ".mwb-obsidian.json"

    def document_source(self, session):
        return root_path(session, self.settings), documents(dataset(session, self.settings))
