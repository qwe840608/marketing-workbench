"""Only explicit platform relationships may regroup comments."""

import hashlib

from sqlalchemy import select

from app.models import AuditLog, Message, Notification, Thread


def thread_key(root):
    return "comment:" + hashlib.sha256(root.encode()).hexdigest()


def relation(reference, post_id):
    ref = reference or {}
    parent = ref.get("parent_id")
    known = ref.get("parent_known") is True or isinstance(parent, str) and bool(parent)
    if parent == post_id:
        parent = None
    if not known:
        return None
    if parent is not None and (not isinstance(parent, str) or not parent or len(parent) > 255):
        return None
    root = ref.get("root_id")
    if not isinstance(root, str) or not root or len(root) > 255:
        root = None
    return parent, root


def refresh(session, thread):
    previous_inbound = thread.last_inbound_at
    rows = list(session.scalars(select(Message).where(Message.thread_id == thread.id)))
    incoming = [m for m in rows if m.direction == "in"]
    outgoing = [m for m in rows if m.direction == "out"]
    thread.last_inbound_at = max((m.sent_at for m in incoming), default=None)
    thread.last_outbound_at = max((m.sent_at for m in outgoing), default=None)
    if thread.last_outbound_at and (
        not thread.last_inbound_at or thread.last_outbound_at >= thread.last_inbound_at
    ):
        thread.status = "replied"
    elif (
        thread.status in {"replied", "closed"}
        and thread.last_inbound_at
        and (previous_inbound is None or thread.last_inbound_at > previous_inbound)
    ):
        thread.status = "pending"


def regroup(session, account_id, post_external_id):
    threads = list(
        session.scalars(
            select(Thread).where(Thread.account_id == account_id, Thread.kind == "comment_thread")
        )
    )
    threads = [t for t in threads if t.source_ref_json.get("post_external_id") == post_external_id]
    if not threads:
        return
    by_thread = {t.id: t for t in threads}
    rows = list(session.scalars(select(Message).where(Message.thread_id.in_(by_thread))))
    by_external = {}
    for m in rows:
        by_external.setdefault(m.external_id, []).append(m)

    def root_for(m, visited):
        if m.id in visited:
            return None
        if m.comment_root_id:
            return m.comment_root_id
        if not m.comment_parent_known:
            return None
        if m.comment_parent_id is None:
            return m.external_id
        parents = by_external.get(m.comment_parent_id, [])
        return root_for(parents[0], visited | {m.id}) if len(parents) == 1 else None

    affected = set()
    for message in rows:
        root = root_for(message, set())
        if not root or len(by_external[message.external_id]) != 1:
            continue
        origin = by_thread[message.thread_id]
        target = next((t for t in threads if t.external_id == thread_key(root)), None)
        if target is None:
            root_message = by_external.get(root, [])
            target = Thread(
                brand_id=origin.brand_id,
                account_id=account_id,
                kind="comment_thread",
                external_id=thread_key(root),
                contact_id=root_message[0].contact_id
                if len(root_message) == 1
                else message.contact_id,
                post_id=origin.post_id,
                source_ref_json={
                    "post_external_id": post_external_id,
                    "root_comment_id": root,
                    "split_from_thread_id": origin.id,
                },
            )
            session.add(target)
            session.flush()
            threads.append(target)
            by_thread[target.id] = target
        if message.external_id == root:
            target.contact_id = message.contact_id
        message.comment_root_id = root
        if message.thread_id == target.id:
            continue
        previous = message.thread_id
        message.thread_id = target.id
        affected.update((previous, target.id))
        # 既有草稿／進度屬於舊段，不擅自複製成每位客人的決定。
        origin.source_ref_json = {**origin.source_ref_json, "legacy_comment_group": True}
        for notice in session.scalars(
            select(Notification).where(Notification.message_id == message.id)
        ):
            notice.thread_id = target.id
            if notice.event_key and notice.event_key.startswith(f"thread:{previous}:cycle:"):
                notice.event_key = notice.event_key.replace(
                    f"thread:{previous}:", f"thread:{target.id}:", 1
                )
        session.add(
            AuditLog(
                brand_id=target.brand_id,
                actor="system",
                action="comment.regroup",
                target_type="message",
                target_id=message.id,
                detail_json={
                    "from_thread_id": previous,
                    "to_thread_id": target.id,
                    "root_comment_id": root,
                },
            )
        )
    session.flush()
    for tid in affected:
        refresh(session, by_thread[tid])
