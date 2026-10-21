from fastapi import APIRouter, Request

from app.api.dependencies import Access
from app.schemas.credentials import CredentialSave, CredentialTest
from app.services import credentials

router = APIRouter(prefix="/api/credentials")


@router.get("")
def listing(request: Request, access: Access):
    return credentials.listing(access, request.app.state.settings)


@router.put("/{name}")
def save(name: str, body: CredentialSave, request: Request, access: Access):
    return credentials.save(access, name, body, request.app.state.settings)


@router.delete("/{name}")
def remove(name: str, version: int, request: Request, access: Access):
    return credentials.remove(access, name, version, request.app.state.settings)


@router.post("/{group}/test")
def test_connection(group: str, body: CredentialTest, request: Request, access: Access):
    return credentials.test_connection(access, group, body, request.app.state.settings)
