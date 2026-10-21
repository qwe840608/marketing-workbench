from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.api.dependencies import Access, Database
from app.schemas.branding import IdentityInput, RulesInput, TemplateInput
from app.schemas.workspace import (
    AutostartInput,
    ExportSettingsInput,
    ObsidianSettingsInput,
)
from app.services import audience, autostart, branding, dashboard, workspace_settings

router = APIRouter(prefix="/api")


@router.get("/workspace/autostart")
def autostart_view(access: Access):
    return autostart.view(access)


@router.put("/workspace/autostart")
def autostart_save(body: AutostartInput, access: Access):
    return autostart.save(access, body)


@router.get("/workspace/status")
def workspace_status(access: Access):
    return autostart.status(access)


@router.get("/dashboard")
def summary(access: Access, brand_id: Annotated[int | None, Query(ge=1)] = None):
    return dashboard.summary(access, brand_id)


@router.get("/dashboard/trends")
def trends(
    access: Access,
    brand_id: Annotated[int | None, Query(ge=1)] = None,
    days: int = 30,
):
    return dashboard.trends(access, brand_id, days)


@router.get("/dashboard/funnel")
def funnel(
    access: Access,
    brand_id: Annotated[int | None, Query(ge=1)] = None,
    days: int = 30,
):
    return dashboard.funnel(access, brand_id, days)


@router.get("/dashboard/audience")
def audience_view(access: Access, brand_id: Annotated[int | None, Query(ge=1)] = None):
    # 只讀本機資料庫；平台資料由每小時排程每天更新一次。
    return audience.view(access, brand_id)


@router.get("/settings/export")
def export_settings(request: Request, access: Access):
    return workspace_settings.export_view(access, request.app.state.settings)


@router.put("/settings/export")
def update_export_settings(body: ExportSettingsInput, request: Request, access: Access):
    return workspace_settings.save_export(access, body, request.app.state.settings)


@router.get("/settings/obsidian")
def obsidian_settings(request: Request, access: Access):
    return workspace_settings.export_view(access, request.app.state.settings, key="obsidian_root")


@router.put("/settings/obsidian")
def update_obsidian_settings(body: ObsidianSettingsInput, request: Request, access: Access):
    return workspace_settings.save_export(
        access, body, request.app.state.settings, key="obsidian_root"
    )


@router.get("/workspace/identity")
def workspace_identity(request: Request, session: Database):
    from app.services.agent_packages import install_info

    return install_info(session, request.app.state.settings)


@router.put("/workspace/identity")
def rename_workspace(body: IdentityInput, access: Access):
    return branding.save_identity(access, body)


@router.get("/settings/templates")
def template_list(access: Access):
    return branding.templates(access)


@router.get("/settings/templates/{name}/preview")
def template_preview(name: str, brand_id: int, access: Access):
    return branding.preview(access, brand_id, name)


@router.post("/settings/templates/apply")
def template_apply(brand_id: int, body: TemplateInput, access: Access):
    return branding.apply_template(access, brand_id, body)


@router.get("/settings/brand-rules")
def brand_rules(brand_id: int, access: Access):
    access.require_brand(brand_id)
    return branding.rules(access.session, brand_id)


@router.put("/settings/brand-rules")
def update_brand_rules(brand_id: int, body: RulesInput, access: Access):
    return branding.save_rules(access, brand_id, body)
