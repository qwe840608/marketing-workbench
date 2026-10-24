"""Workspace identity and atomic, previewed brand templates."""

import hashlib
import json

from fastapi import HTTPException

from app.config import REPO_ROOT
from app.models import PromptVersion
from app.services import ideation_settings, prompts, roles, settings_store
from app.services.posts import _begin_ingest

DEFAULT_NAME = "行銷管理工作檯"
NAME_KEY = "workspace.display_name"


def identity(session):
    row = settings_store.get(session, NAME_KEY)
    return {"name": row.value_json if row else DEFAULT_NAME, "version": settings_store.version(row)}


def admin(access):
    if not roles.can(access, "settings.manage"):
        raise HTTPException(403, "僅管理員可修改工作區名稱及套用範本")


def put_setting(session, key, value):
    row = settings_store.get(session, key)
    settings_store.put(session, key, value, row)


def save_identity(access, body):
    admin(access)
    session = access.session
    session.commit()
    with session.begin():
        audit = _begin_ingest(session, "workspace.rename")
        before = identity(session)
        if before["version"] != body.version:
            raise HTTPException(409, "工作區名稱已更新，請重新載入")
        put_setting(session, NAME_KEY, body.name)
        audit.actor = f"staff:{access.staff.id}"
        audit.detail_json = {"before": before["name"], "after": body.name}
    return identity(session)


def rules(session, brand_id):
    row = settings_store.get(session, f"brand.rules.{brand_id}")
    return row.value_json if row else {"forbidden_phrases": []}


def load_template(name):
    if name not in {"creator", "blank"}:
        raise HTTPException(404, "找不到範本")
    return json.loads((REPO_ROOT / "templates" / f"{name}.json").read_text(encoding="utf-8"))


def templates(access):
    admin(access)
    return [{"id": name, "name": load_template(name)["name"]} for name in ("creator", "blank")]


def state(session, brand_id):
    cfg = ideation_settings.config(session, brand_id)
    prompt = prompts.current(session, brand_id)
    return {
        "topics": cfg.topics,
        "forbidden_phrases": rules(session, brand_id).get("forbidden_phrases", []),
        "brand_prompt": prompt.content if prompt else "",
        "prompt_revision": prompt.revision if prompt else 0,
        "meeting_version": cfg.version,
    }


def preview(access, brand_id, name):
    admin(access)
    access.require_brand(brand_id)
    before = state(access.session, brand_id)
    template = load_template(name)
    after = {k: template[k] for k in ("topics", "forbidden_phrases", "brand_prompt")}
    token = hashlib.sha256(
        json.dumps([brand_id, name, before, after], ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return {"before": before, "after": after, "token": token, "template": name}


def apply_template_data(session, brand_id, name, actor, reset_meeting=False):
    template = load_template(name)
    cfg = ideation_settings.config(session, brand_id)
    from app.schemas.ideation import MeetingConfig

    if reset_meeting:
        cfg = MeetingConfig(topics=["其他"])
    value = cfg.model_dump(mode="json", exclude={"version"})
    value["topics"] = template["topics"]
    put_setting(session, f"ideation.brand.{brand_id}", value)
    put_setting(
        session, f"brand.rules.{brand_id}", {"forbidden_phrases": template["forbidden_phrases"]}
    )
    old = prompts.current(session, brand_id)
    session.add(
        PromptVersion(
            scope=prompts.scope(brand_id),
            task="draft",
            brand_id=brand_id,
            revision=(old.revision if old else 0) + 1,
            content=template["brand_prompt"],
            actor=actor,
        )
    )


def apply_template(access, brand_id, body):
    admin(access)
    access.require_brand(brand_id, write=True)
    session = access.session
    session.commit()
    with session.begin():
        audit = _begin_ingest(session, "brand.template.apply")
        change = preview(access, brand_id, body.template)
        if change["token"] != body.token:
            raise HTTPException(409, "品牌設定或範本已變更，請重新預覽")
        apply_template_data(session, brand_id, body.template, f"staff:{access.staff.id}")
        audit.actor, audit.brand_id = f"staff:{access.staff.id}", brand_id
        audit.detail_json = change
    return {"applied": True}


def save_rules(access, brand_id, body):
    admin(access)
    access.require_brand(brand_id, write=True)
    session = access.session
    session.commit()
    with session.begin():
        audit = _begin_ingest(session, "brand.rules.update")
        before = rules(session, brand_id)
        if before != body.before:
            raise HTTPException(409, "品牌禁語已更新，請重新載入")
        after = {"forbidden_phrases": body.forbidden_phrases}
        put_setting(session, f"brand.rules.{brand_id}", after)
        audit.actor, audit.brand_id = f"staff:{access.staff.id}", brand_id
        audit.detail_json = {"before": before, "after": after}
    return after
