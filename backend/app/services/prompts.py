"""Versioned prompts are the single source for generation, review and invalidation."""

import difflib

from fastapi import HTTPException
from sqlalchemy import select

from app.models import PromptVersion, Staff
from app.services.posts import _begin_ingest

# Historical key is shared by marketing prompts; keep existing versions without a migration.
TASK = "draft"


def scope(brand_id):
    return f"brand:{brand_id}" if brand_id is not None else "shared"


def current(session, brand_id=None, task=TASK):
    return session.scalar(
        select(PromptVersion)
        .where(PromptVersion.scope == scope(brand_id), PromptVersion.task == task)
        .order_by(PromptVersion.revision.desc())
        .limit(1)
    )


def context(session, brand_id):
    from app.services.branding import rules

    shared, brand = current(session), current(session, brand_id)
    return {
        "forbidden_phrases": rules(session, brand_id).get("forbidden_phrases", []),
        "base_prompt": shared.content if shared else "",
        "brand_rules": brand.content if brand else "",
        "prompt_versions": {
            "shared": shared.revision if shared else 0,
            "brand": brand.revision if brand else 0,
        },
    }


def authorize(access, brand_id, write=False):
    if brand_id is not None:
        access.require_brand(brand_id, write=write)
    elif write and access.staff.role != "admin":
        raise HTTPException(403, "共用 prompt 僅管理員可修改")


def history(access, brand_id=None):
    authorize(access, brand_id)
    rows = list(
        access.session.scalars(
            select(PromptVersion)
            .where(PromptVersion.scope == scope(brand_id), PromptVersion.task == TASK)
            .order_by(PromptVersion.revision)
        )
    )
    result, previous = [], ""
    for row in rows:
        author = row.actor
        if author.startswith("staff:"):
            staff = access.session.get(Staff, int(author.split(":")[1]))
            author = staff.display_name if staff else "已停用帳號"
        result.append(
            dict(
                revision=row.revision,
                content=row.content,
                actor=author,
                created_at=row.created_at,
                restored_from=row.restored_from,
                diff="\n".join(
                    difflib.unified_diff(
                        previous.splitlines(),
                        row.content.splitlines(),
                        fromfile="前一版本",
                        tofile="此版本",
                        lineterm="",
                    )
                ),
            )
        )
        previous = row.content
    return {"revision": rows[-1].revision if rows else 0, "versions": result[::-1]}


def save(access, brand_id, body, restore=False):
    authorize(access, brand_id, write=True)
    session, staff_id = access.session, access.staff.id
    session.commit()
    with session.begin():
        audit = _begin_ingest(session, "ai.prompt.restore" if restore else "ai.prompt.save")
        authorize(access, brand_id, write=True)
        latest = current(session, brand_id)
        revision = latest.revision if latest else 0
        if revision != body.revision:
            raise HTTPException(409, "prompt 已更新，請重新載入版本")
        if restore:
            old = session.scalar(
                select(PromptVersion).where(
                    PromptVersion.scope == scope(brand_id),
                    PromptVersion.task == TASK,
                    PromptVersion.revision == body.restore_revision,
                )
            )
            if old is None:
                raise HTTPException(404, "找不到 prompt 版本")
            content = old.content
        else:
            content = body.content
        session.add(
            PromptVersion(
                scope=scope(brand_id),
                task=TASK,
                brand_id=brand_id,
                revision=revision + 1,
                content=content,
                actor=f"staff:{staff_id}",
                restored_from=body.restore_revision if restore else None,
            )
        )
        audit.actor, audit.brand_id, audit.target_type = f"staff:{staff_id}", brand_id, "prompt"
        audit.detail_json = {
            "scope": scope(brand_id),
            "task": TASK,
            "revision": revision + 1,
            "restored_from": body.restore_revision if restore else None,
        }
    return history(access, brand_id)
