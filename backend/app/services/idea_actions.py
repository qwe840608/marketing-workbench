"""Evidence-bound manual edits and restore of a single idea; the report keeps its card positions."""

import copy
from uuid import uuid4

from fastapi import HTTPException

from app.db import ensure_write
from app.models import AuditLog
from app.models.base import utc_now
from app.services import ideation


def audit(session, row, action, job):
    session.add(
        AuditLog(
            brand_id=row.brand_id,
            actor=f"staff:{job['staff_id']}",
            action="ideation.ideas." + action,
            target_type="ideation_report",
            target_id=row.id,
            detail_json={"indices": job["indices"], "job_id": job["id"]},
        )
    )


def restore(access, report_id, index, settings, factory):
    ensure_write(access.session)
    row = ideation.get(access, report_id)
    access.require_brand(row.brand_id, write=True)
    if row.status != "ready":
        raise HTTPException(409, "產生中不能還原主題")
    data = copy.deepcopy(row.data_json)
    history = data.get("ideas_history", {}).get(str(index), [])
    if not history or index < 0 or index >= len(data.get("ideas", [])):
        raise HTTPException(422, "沒有可還原的上一版")
    previous = history.pop()
    replaced = data["ideas"][index]
    data["ideas"][index] = previous["idea"]
    data["ideas_revision"] = data.get("ideas_revision", 1) + 1
    data["ideas_versions"] = [
        *data.get("ideas_versions", []),
        {
            "index": index,
            "restored_at": utc_now().isoformat(),
            "idea": replaced,
            "previous": previous,
        },
    ]
    row.data_json = data
    row.export_json = {}
    audit(
        access.session,
        row,
        "restore",
        dict(id=str(uuid4()), indices=[index], staff_id=access.staff.id),
    )
    access.session.commit()
    from app.services.ideation_exports import export_report

    exported = export_report(factory, settings, report_id)
    # 內容已提交；匯出失敗仍回成功，另附原因。
    return {**ideation.view(row), "export_error": exported["error"]}


def edit(access, report_id, index, body, settings, factory, *, via=None):
    ensure_write(access.session)
    row = ideation.get(access, report_id)
    access.require_brand(row.brand_id, write=True)
    if row.status != "ready":
        raise HTTPException(409, "請等待主題處理完成後再編輯")
    data = copy.deepcopy(row.data_json)
    if data.get("ideas_revision", 1) != body.version:
        raise HTTPException(409, "主題已更新，請重新載入後再編輯")
    if index < 0 or index >= len(data.get("ideas", [])):
        raise HTTPException(404, "找不到主題")
    old = data["ideas"][index]
    data.setdefault("ideas_history", {}).setdefault(str(index), []).append(
        {"idea": old, "at": utc_now().isoformat()}
    )
    data["ideas"][index] = {**old, **body.model_dump(exclude={"version"}), "edited": True}
    data["ideas_revision"] = body.version + 1
    row.data_json, row.export_json = data, {}
    access.session.add(AuditLog(
        actor=f"staff:{access.staff.id}", brand_id=row.brand_id,
        action="ideation.ideas.edit", target_type="ideation_report", target_id=row.id,
        detail_json={"report_id": row.id, "index": index, **({"via": via} if via else {})},
    ))
    access.session.commit()
    from app.services.ideation_exports import export_report

    exported = export_report(factory, settings, report_id)
    # 內容已提交；匯出失敗仍回成功，另附原因。
    return {**ideation.view(row), "export_error": exported["error"]}
