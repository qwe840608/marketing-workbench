"""Unauthenticated downloads within the existing local/Tailscale boundary."""

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.api.dependencies import Database
from app.services import agent_auth
from app.services import agent_packages as service

router = APIRouter()


@router.get("/plugin/marketplace.json")
def marketplace(request: Request, session: Database):
    return service.marketplace(session, agent_auth.origin_for(request))


def download(request, version, codex=False, desktop=False):
    origin = agent_auth.origin_for(request)
    content, name = service.download(origin, version, codex=codex, desktop=desktop)
    return Response(content, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/plugin/mwb-{version}.zip")
def claude(request: Request, version: str):
    return download(request, version)


@router.get("/plugin/codex/mwb-codex-{version}.zip")
def codex(request: Request, version: str):
    return download(request, version, codex=True)


@router.get("/plugin/desktop/mwb-{version}.mcpb")
def desktop(request: Request, version: str):
    return download(request, version, desktop=True)
