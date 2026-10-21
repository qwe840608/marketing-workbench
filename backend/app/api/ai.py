from fastapi import APIRouter, Request

from app.api.dependencies import Access
from app.schemas.ai import AISettings
from app.services import ai

router = APIRouter(prefix="/api")


@router.get("/ai/execution-options")
def execution_options(brand_id: int, request: Request, access: Access):
    return ai.execution_options(access, brand_id, request.app.state.settings)


@router.get("/ai/settings")
def configuration(brand_id: int, request: Request, access: Access):
    return ai.configuration_view(access, brand_id, request.app.state.settings)


@router.put("/ai/settings")
def update(brand_id: int, body: AISettings, request: Request, access: Access):
    return ai.update_configuration(access, brand_id, body, request.app.state.settings)
