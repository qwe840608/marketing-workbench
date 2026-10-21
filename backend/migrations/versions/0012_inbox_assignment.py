"""Brand assignees and evidence-based comment conversations (frozen data migration)."""

import hashlib
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "brand_people",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("brand_id", sa.Integer(), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "role IN ('owner', 'customer_service', 'other')", name="brand_person_role"
        ),
        sa.UniqueConstraint("id", "brand_id"),
    )
    op.create_index("ix_brand_people_brand_id", "brand_people", ["brand_id"])
    with op.batch_alter_table("threads") as b:
        b.add_column(sa.Column("owner_person_id", sa.Integer()))
        b.add_column(
            sa.Column("assignment_mode", sa.String(6), nullable=False, server_default="auto")
        )
        b.create_foreign_key(
            "fk_threads_owner_person_id_brand_people",
            "brand_people",
            ["owner_person_id", "brand_id"],
            ["id", "brand_id"],
        )
        b.create_check_constraint(
            "single_assignee", "owner_staff_id IS NULL OR owner_person_id IS NULL"
        )
        b.create_check_constraint("assignment_mode", "assignment_mode IN ('auto', 'manual')")
    op.execute("ALTER TABLE messages ADD COLUMN comment_parent_id VARCHAR(255)")
    op.execute("ALTER TABLE messages ADD COLUMN comment_root_id VARCHAR(255)")
    op.execute("ALTER TABLE messages ADD COLUMN comment_parent_known BOOLEAN NOT NULL DEFAULT 0")
    db = op.get_bind()
    metadata = sa.MetaData()
    metadata.reflect(db)
    threads, messages, events, accounts, audit, notices = [
        metadata.tables[k]
        for k in ("threads", "messages", "raw_events", "accounts", "audit_log", "notifications")
    ]
    # 有人工工作流稽核的既有指派（含清空）保守保留；其餘求職規則仍為自動。
    modes = {
        t.id: "manual"
        for t in db.execute(sa.select(threads.c.id).where(threads.c.owner_staff_id.is_not(None)))
    }
    for log in db.execute(
        sa.select(audit)
        .where(audit.c.action.in_(["thread.workflow", "classification.assign_supervisor"]))
        .order_by(audit.c.at, audit.c.id)
    ).mappings():
        if log["action"] == "classification.assign_supervisor":
            modes[log["target_id"]] = "auto"
        elif "owner_staff_id" in log["detail_json"].get("after", {}):
            modes[log["target_id"]] = "manual"
    db.execute(
        threads.update()
        .where(threads.c.id.in_([tid for tid, mode in modes.items() if mode == "manual"]))
        .values(assignment_mode="manual")
    )
    account_map = {}
    for a in db.execute(sa.select(accounts)).mappings():
        key = a["platform"], a["external_id"]
        account_map[key] = None if key in account_map else a["id"]
    evidence, conflicts = {}, set()

    def dictionaries(value):
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    def record(aid, cid, parent, root=None, post=None):
        def valid(value):
            return (
                isinstance(value, str)
                and 0 < len(value) <= 255
                and not any(c.isspace() for c in value)
            )

        if not valid(cid) or (parent is not None and not valid(parent)):
            return
        k = (aid, cid)
        previous = evidence.get(k)
        value = (parent, root, post)
        if previous and previous[0] != parent:
            conflicts.add(k)
        elif previous is None or root:
            evidence[k] = value

    for event in db.execute(sa.select(events).where(events.c.processed.is_(True))).mappings():
        aid = account_map.get((event["platform"], event["account_external_id"]))
        p = event["payload_json"]
        if not aid or not isinstance(p, dict):
            continue
        if event["source"] == "poll" and isinstance(p.get("edge"), str):
            resource, _, edge = p["edge"].rpartition("/")
            for item in dictionaries(p.get("data")):
                if isinstance(item, dict) and edge in {"comments", "replies"}:
                    record(
                        aid,
                        item.get("id"),
                        resource if edge == "replies" else None,
                        resource if edge == "replies" else item.get("id"),
                        resource if edge == "comments" else None,
                    )
        if not event["signature_ok"]:
            continue
        for entry in dictionaries(p.get("entry")):
            for change in dictionaries(entry.get("changes")):
                v = change.get("value", {})
                if (
                    not isinstance(v, dict)
                    or change.get("field") not in {"feed", "comments"}
                    or "parent_id" not in v
                ):
                    continue
                media = v.get("media")
                post = v.get("post_id") or (media.get("id") if isinstance(media, dict) else None)
                parent = v["parent_id"]
                record(
                    aid,
                    v.get("comment_id") or v.get("id"),
                    None if parent == post else parent,
                    post=post,
                )
    originals = {
        t["id"]: dict(t)
        for t in db.execute(sa.select(threads).where(threads.c.kind == "comment_thread")).mappings()
    }
    for old in originals.values():
        db.execute(
            threads.update()
            .where(threads.c.id == old["id"])
            .values(source_ref_json={**old["source_ref_json"], "legacy_comment_group": True})
        )
    rows = [
        dict(m)
        for m in db.execute(
            sa.select(messages).where(messages.c.thread_id.in_(originals))
        ).mappings()
    ]
    for m in rows:
        t = originals[m["thread_id"]]
        k = (t["account_id"], m["external_id"])
        if k in evidence and k not in conflicts:
            parent, root, post = evidence[k]
            if post and t["source_ref_json"].get("post_external_id", t["external_id"]) != post:
                continue
            m.update(comment_parent_known=True, comment_parent_id=parent, comment_root_id=root)
            db.execute(
                messages.update()
                .where(messages.c.id == m["id"])
                .values(comment_parent_known=True, comment_parent_id=parent, comment_root_id=root)
            )
    by_external = {}
    for m in rows:
        by_external.setdefault(
            (originals[m["thread_id"]]["account_id"], m["external_id"]), []
        ).append(m)

    def root_for(m, aid, visited):
        if m["id"] in visited or not m["comment_parent_known"]:
            return None
        if m["comment_root_id"]:
            return m["comment_root_id"]
        if m["comment_parent_id"] is None:
            return m["external_id"]
        parents = by_external.get((aid, m["comment_parent_id"]), [])
        if len(parents) == 1:
            own_post = originals[m["thread_id"]]["source_ref_json"].get("post_external_id")
            parent_post = originals[parents[0]["thread_id"]]["source_ref_json"].get(
                "post_external_id"
            )
            if own_post != parent_post:
                return None
        return root_for(parents[0], aid, visited | {m["id"]}) if len(parents) == 1 else None

    now = datetime.now(UTC).isoformat(timespec="microseconds")
    targets, affected = {}, set()
    for m in rows:
        old = originals[m["thread_id"]]
        root = root_for(m, old["account_id"], set())
        if not root or len(by_external[(old["account_id"], m["external_id"])]) != 1:
            continue
        k = (old["account_id"], root)
        if k not in targets:
            root_rows = by_external.get(k, [])
            if len(root_rows) == 1 and originals[root_rows[0]["thread_id"]]["source_ref_json"].get(
                "post_external_id"
            ) != old["source_ref_json"].get("post_external_id"):
                continue
            ref = {
                "post_external_id": old["source_ref_json"].get(
                    "post_external_id", old["external_id"]
                ),
                "root_comment_id": root,
                "split_from_thread_id": old["id"],
            }
            value = dict(old)
            value.pop("id")
            # 舊的整篇貼文進度與草稿留在原段，不複製為每位客人的決策。
            value.update(
                external_id="comment:" + hashlib.sha256(root.encode()).hexdigest(),
                source_ref_json=ref,
                contact_id=root_rows[0]["contact_id"] if len(root_rows) == 1 else m["contact_id"],
                owner_staff_id=None,
                owner_person_id=None,
                assignment_mode="auto",
                status="pending",
                stage="inquiry",
                list_color=None,
                booking_date=None,
                booking_units=None,
                last_inbound_at=None,
                last_outbound_at=None,
                version=1,
                created_at=now,
                updated_at=now,
            )
            targets[k] = db.execute(threads.insert().values(**value)).inserted_primary_key[0]
        target_id = targets[k]
        db.execute(
            messages.update()
            .where(messages.c.id == m["id"])
            .values(thread_id=target_id, comment_root_id=root)
        )
        for notice in db.execute(
            sa.select(notices).where(notices.c.message_id == m["id"])
        ).mappings():
            event_key = notice["event_key"]
            if event_key and event_key.startswith(f"thread:{old['id']}:cycle:"):
                event_key = event_key.replace(f"thread:{old['id']}:", f"thread:{target_id}:", 1)
            db.execute(
                notices.update()
                .where(notices.c.id == notice["id"])
                .values(thread_id=target_id, event_key=event_key)
            )
        affected.update((old["id"], target_id))
        db.execute(
            audit.insert().values(
                brand_id=old["brand_id"],
                actor="system:migration",
                action="comment.regroup",
                target_type="message",
                target_id=m["id"],
                detail_json={
                    "from_thread_id": old["id"],
                    "to_thread_id": target_id,
                    "root_comment_id": root,
                },
                at=now,
                created_at=now,
                updated_at=now,
            )
        )
    for tid in affected:
        current = list(
            db.execute(sa.select(messages).where(messages.c.thread_id == tid)).mappings()
        )
        incoming = max((m["sent_at"] for m in current if m["direction"] == "in"), default=None)
        outgoing = max((m["sent_at"] for m in current if m["direction"] == "out"), default=None)
        values = dict(last_inbound_at=incoming, last_outbound_at=outgoing)
        if tid in originals:
            values["source_ref_json"] = {
                **originals[tid]["source_ref_json"],
                "legacy_comment_group": True,
            }
        else:
            values["status"] = (
                "replied" if outgoing and (not incoming or outgoing >= incoming) else "pending"
            )
        db.execute(threads.update().where(threads.c.id == tid).values(**values))


def downgrade():
    db = op.get_bind()
    if (
        db.execute(sa.text("SELECT 1 FROM brand_people LIMIT 1")).first()
        or db.execute(
            sa.text("SELECT 1 FROM messages WHERE comment_parent_known = 1 LIMIT 1")
        ).first()
        or db.execute(
            sa.text("SELECT 1 FROM threads WHERE assignment_mode = 'manual' LIMIT 1")
        ).first()
    ):
        raise RuntimeError("已使用新的留言關係或指派；請以升級前的一致備份還原，避免丟失資料")
    # 原有 contact_id 是 inline FK；不重建 messages，保留 0004 的可逆定義。
    for column in ("comment_parent_id", "comment_root_id", "comment_parent_known"):
        op.execute(f"ALTER TABLE messages DROP COLUMN {column}")
    with op.batch_alter_table("threads") as b:
        b.drop_constraint("fk_threads_owner_person_id_brand_people", type_="foreignkey")
        b.drop_constraint(op.f("ck_threads_single_assignee"), type_="check")
        b.drop_constraint(op.f("ck_threads_assignment_mode"), type_="check")
        b.drop_column("owner_person_id")
        b.drop_column("assignment_mode")
    op.drop_table("brand_people")
