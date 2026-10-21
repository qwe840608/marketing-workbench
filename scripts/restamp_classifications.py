"""Restamp only classifications proven to match explicitly selected old prompts.

No application settings, environment files, workers or platform clients are loaded.
Revision 0 means that scope had no prompt. Dry-run opens the existing DB read-only.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import create_engine, event, select, update
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.models import AuditLog, Classification, Message, PromptVersion  # noqa: E402
from app.services import classify, prompts  # noqa: E402
from app.services.branding import rules  # noqa: E402


def historical_context(session, brand_id, shared_revision, brand_revision):
    def content(scope_brand, revision):
        if revision == 0:
            return ""
        row = session.scalar(select(PromptVersion).where(
            PromptVersion.scope == prompts.scope(scope_brand),
            PromptVersion.task == prompts.TASK,
            PromptVersion.revision == revision,
        ))
        if row is None:
            raise ValueError(f"Missing prompt revision: {prompts.scope(scope_brand)}:{revision}")
        return row.content

    # Preserve the legacy key order: fingerprint JSON deliberately is not sorted.
    # Forbidden phrases have no revision history; any change safely fails the hash match.
    return {
        "forbidden_phrases": rules(session, brand_id).get("forbidden_phrases", []),
        "base_prompt": content(None, shared_revision),
        "brand_rules": content(brand_id, brand_revision),
        "prompt_versions": {"shared": shared_revision, "brand": brand_revision},
    }


def restamp(database, shared_revision, brand_revision, *, apply=False):
    if shared_revision < 0 or brand_revision < 0:
        raise ValueError("Prompt revisions must be non-negative")
    path = Path(database).resolve(strict=True)
    if not path.is_file():
        raise ValueError("Database must be an existing file")
    # mode=rw also refuses accidental creation; dry-run never changes journal mode.
    engine = create_engine("sqlite+pysqlite://", creator=lambda: sqlite3.connect(
        path.as_uri() + ("?mode=rw" if apply else "?mode=ro"),
        uri=True, isolation_level=None, timeout=5,
    ), hide_parameters=True)

    @event.listens_for(engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    stats = {"total": 0, "matched": 0, "updated": 0, "unmatched": 0}
    try:
        with Session(engine) as session, session.begin():
            contexts = {}
            for row in session.scalars(select(Classification).order_by(Classification.id)):
                stats["total"] += 1
                message = session.get(Message, row.message_id)
                if message is None:
                    stats["unmatched"] += 1
                    continue
                new_context, brand_id = classify.context_for(session, message)
                if brand_id not in contexts:
                    contexts[brand_id] = historical_context(
                        session, brand_id, shared_revision, brand_revision
                    )
                old_context = {**contexts[brand_id], **new_context}
                old_hash = classify.fingerprint(message.text, old_context)
                if old_hash != row.input_hash:
                    stats["unmatched"] += 1
                    continue
                stats["matched"] += 1
                if apply:
                    new_hash = classify.fingerprint(message.text, new_context)
                    # Restamping is not a new judgement; preserve all result timestamps.
                    session.execute(update(Classification).where(
                        Classification.id == row.id
                    ).values(input_hash=new_hash, updated_at=row.updated_at))
                    stats["updated"] += 1
                    session.add(AuditLog(
                        brand_id=brand_id, actor="system:restamp-classifications",
                        action="classification.restamp", target_type="classification",
                        target_id=row.id, detail_json={
                            "before": old_hash, "after": new_hash,
                            "shared_revision": shared_revision,
                            "brand_revision": brand_revision,
                        },
                    ))
        return stats
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--shared-revision", type=int, required=True)
    parser.add_argument("--brand-revision", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = restamp(args.database, args.shared_revision, args.brand_revision, apply=args.apply)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
