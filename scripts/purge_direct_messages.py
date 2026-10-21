"""Explicit-path DM purge. Preview by default; never loads application settings."""

import argparse
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def raw_kind(payload):
    """Only positive source evidence permits deletion; mixed envelopes survive."""
    if not isinstance(payload, dict):
        return None
    sources = [
        key
        for key in ("payload", "messages", "message", "entry", "events")
        if key in payload
    ]
    if len(sources) > 1:
        kinds = {raw_kind({key: payload[key]}) for key in sources}
        return kinds.pop() if len(kinds) == 1 and None not in kinds else None
    if "payload" in payload:
        return raw_kind(payload["payload"])
    messages = payload.get("messages")
    if "message" in payload and isinstance(payload["message"], dict):
        messages = [payload["message"]]
    if isinstance(messages, list) and messages:
        if not all(isinstance(m, dict) for m in messages):
            return None
        kinds = {m.get("kind") for m in messages if isinstance(m, dict)}
        return (
            "dm"
            if kinds == {"dm"} and len(kinds)
            else "comment"
            if kinds == {"comment_thread"}
            else None
        )
    entries = payload.get("entry")
    if isinstance(entries, list) and entries:
        if all(
            isinstance(e, dict) and e.get("messaging") and not e.get("changes")
            for e in entries
        ):
            return "dm"
        if all(
            isinstance(e, dict) and e.get("changes") and not e.get("messaging")
            for e in entries
        ):
            return "comment"
    events = payload.get("events")
    if (
        isinstance(events, list)
        and events
        and all(
            isinstance(e, dict)
            and e.get("type") == "message"
            and isinstance(e.get("source"), dict)
            and e["source"].get("type") == "user"
            for e in events
        )
    ):
        return "dm"
    return None


def ids(db, table, predicate="1", args=()):
    return {r[0] for r in db.execute(f"SELECT id FROM {table} WHERE {predicate}", args)}


def export_path(root, relative):
    from app.services.export_data import destination

    candidate = root
    for part in Path(relative).parts:
        candidate /= part
        if candidate.is_symlink() or candidate.is_junction():
            raise ValueError("Linked export paths require manual review; purge aborted")
    return destination(root, relative)


def plan(db, export_root=None):
    tables = {
        r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    result = {}
    result["threads"] = ids(db, "threads", "kind='dm'")
    dm_threads = "SELECT id FROM threads WHERE kind='dm'"
    dm_messages = f"SELECT id FROM messages WHERE thread_id IN ({dm_threads})"
    result["messages"] = ids(db, "messages", f"thread_id IN ({dm_threads})")
    for table in (
        "classifications",
        "topic_annotations",
        "inbound_jobs",
        "line_reply_credentials",
    ):
        if table in tables:
            result[table] = ids(db, table, f"message_id IN ({dm_messages})")
    result["drafts"] = ids(db, "drafts")
    if "send_attempts" in tables:
        result["send_attempts"] = ids(
            db, "send_attempts", f"thread_id IN ({dm_threads})"
        )
    result["notifications"] = ids(
        db,
        "notifications",
        f"thread_id IN ({dm_threads}) OR message_id IN ({dm_messages})",
    )
    notices = list(db.execute("SELECT id, delivery_id FROM notifications"))
    affected = {
        r["delivery_id"] for r in notices if r["id"] in result["notifications"]
    } - {None}
    shared = {
        r["delivery_id"] for r in notices if r["id"] not in result["notifications"]
    } & affected
    # A delivery caches original text. Remove the cache, detach surviving comment notices.
    result["notification_deliveries"] = affected
    candidates = {
        r[0]
        for r in db.execute(
            f"SELECT contact_id FROM threads WHERE id IN ({dm_threads}) UNION SELECT contact_id FROM messages WHERE id IN ({dm_messages})"
        )
    } - {None}
    retained = {
        r[0]
        for r in db.execute(
            f"SELECT contact_id FROM threads WHERE id NOT IN ({dm_threads}) UNION SELECT contact_id FROM messages WHERE id NOT IN ({dm_messages})"
        )
    } - {None}
    result["contacts"] = candidates - retained
    result["raw_events"], uncertain = set(), []
    for row in db.execute("SELECT id, platform, payload_json FROM raw_events"):
        try:
            kind = raw_kind(json.loads(row["payload_json"]))
        except (ValueError, TypeError, RecursionError):
            kind = None
        # LINE 官方帳號沒有貼文留言；收進來的事件（含群組聊天）都屬於私訊管道。
        if row["platform"] == "line":
            kind = "dm"
        if kind == "dm":
            result["raw_events"].add(row["id"])
        elif kind is None:
            uncertain.append(row["id"])
    files = []
    if export_root is not None:
        # Reuse only the pure filename helper, never Settings or export-root configuration.
        from app.services.export_data import segment

        root = Path(export_root).resolve(strict=True)
        contacts = list(
            db.execute(
                "SELECT c.*, b.slug FROM contacts c JOIN brands b ON b.id=c.brand_id"
            )
        )
        retained_prefixes = {}
        for row in contacts:
            if row["id"] not in result["contacts"]:
                key = (segment(row["slug"]).casefold(), row["platform"])
                retained_prefixes.setdefault(key, []).append(
                    segment(row["external_id"]).casefold() + "_"
                )
        for row in contacts:
            if row["id"] not in result["contacts"]:
                continue
            directory = export_path(
                root, f"{segment(row['slug'])}/users/{row['platform']}"
            )
            if not directory.is_dir():
                continue
            prefix = segment(row["external_id"]) + "_"
            for path in directory.iterdir():
                ambiguous = any(
                    path.name.casefold().startswith(p)
                    for p in retained_prefixes.get(
                        (segment(row["slug"]).casefold(), row["platform"]), ()
                    )
                )
                if (
                    path.suffix.lower() in {".md", ".docx"}
                    and path.name.startswith(prefix)
                    and not ambiguous
                ):
                    files.append(export_path(root, path.relative_to(root)))
        # Historical Word exports identify the thread, rather than its contact.
        for row in db.execute(
            "SELECT t.id, b.slug, a.platform FROM threads t JOIN brands b ON b.id=t.brand_id JOIN accounts a ON a.id=t.account_id WHERE t.kind='dm'"
        ):
            directory = export_path(
                root, f"{segment(row['slug'])}/users/{row['platform']}"
            )
            if directory.is_dir():
                for path in directory.iterdir():
                    if re.fullmatch(
                        rf"對話_{row['id']}_\d{{8}}_\d{{6}}_\d{{6}}\.docx", path.name
                    ):
                        files.append(export_path(root, path.relative_to(root)))
    return result, sorted(set(files)), uncertain, shared


def purge(database, export_root=None, apply=False):
    database = Path(database).resolve(strict=True)
    db = sqlite3.connect(
        database.as_uri() + ("?mode=rw" if apply else "?mode=ro"),
        uri=True,
        isolation_level=None,
    )
    db.row_factory = sqlite3.Row
    removed = {}
    try:
        db.execute("PRAGMA foreign_keys=ON")
        if not apply:
            db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Existing foreign key violations; purge aborted")
        targets, files, uncertain, shared = plan(db, export_root)
        report = {
            "apply": apply,
            "counts": {t: len(v) for t, v in targets.items()},
            "files": [str(p) for p in files],
            "uncertain_raw_event_ids": uncertain,
            "shared_deliveries": len(shared),
        }
        if apply and (any(targets.values()) or files):
            for delivery in targets["notification_deliveries"]:
                db.execute(
                    "UPDATE notifications SET delivery_id=NULL WHERE delivery_id=?",
                    (delivery,),
                )
            for table in (
                "classifications",
                "topic_annotations",
                "inbound_jobs",
                "line_reply_credentials",
                "drafts",
                "send_attempts",
                "notifications",
                "notification_deliveries",
                "messages",
                "threads",
                "contacts",
                "raw_events",
            ):
                db.executemany(
                    f"DELETE FROM {table} WHERE id=?",
                    [(i,) for i in targets.get(table, ())],
                )
            if db.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Foreign key violations; purge rolled back")
            stamp = datetime.now(UTC).isoformat()
            db.execute(
                "INSERT INTO audit_log(actor,action,target_type,detail_json,at,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (
                    "operator",
                    "data.purge_dm",
                    "database",
                    json.dumps({**report["counts"], "files": len(files)}),
                    stamp,
                    stamp,
                    stamp,
                ),
            )
            # Restore removed bytes on any failure before commit. Deployment backup remains mandatory.
            for path in files:
                removed[path] = path.read_bytes()
                path.unlink()
        db.execute("COMMIT")
        return report
    except BaseException:
        if db.in_transaction:
            db.execute("ROLLBACK")
        for path, content in removed.items():
            path.write_bytes(content)
        raise
    finally:
        db.close()


def main():
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--export-root", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            purge(args.database, args.export_root, args.apply),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
