from fastapi import APIRouter, Request

from app.api.dependencies import Access
from app.schemas.ai_settings import KeySave, KeyTest, PromptEdit, PromptRestore
from app.services import ai_keys, prompts

router = APIRouter(prefix="/api/ai")


@router.get("/keys")
def keys(request: Request, access: Access):
    return ai_keys.listing(access, request.app.state.settings)


@router.post("/keys/{provider}/test")
def test_key(provider: str, body: KeyTest, request: Request, access: Access):
    return ai_keys.test_connection(access, provider, body, request.app.state.settings)


@router.put("/keys/{provider}")
def save_key(provider: str, body: KeySave, request: Request, access: Access):
    return ai_keys.save(access, provider, body, request.app.state.settings)


@router.delete("/keys/{provider}")
def delete_key(provider: str, version: int, request: Request, access: Access):
    return ai_keys.remove(access, provider, version, request.app.state.settings)


@router.get("/prompts")
def history(access: Access, brand_id: int | None = None):
    return prompts.history(access, brand_id)


@router.put("/prompts")
def save_prompt(body: PromptEdit, access: Access, brand_id: int | None = None):
    return prompts.save(access, brand_id, body)


@router.post("/prompts/restore")
def restore_prompt(body: PromptRestore, access: Access, brand_id: int | None = None):
    return prompts.save(access, brand_id, body, restore=True)
