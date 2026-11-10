from fastapi import APIRouter, Request

from app.api.dependencies import Access
from app.schemas.flows import ApproveInput, EnableInput, FlowInput
from app.services import flows

router = APIRouter(prefix="/api")


@router.get("/flows")
def listing(access: Access, brand_id: int | None = None):
    return flows.listing(access, brand_id)


@router.post("/flows", status_code=201)
def create(body: FlowInput, access: Access):
    return flows.save(access, body)


@router.get("/flows/{identity}")
def detail(identity: int, access: Access):
    return flows.detail(access, identity)


@router.put("/flows/{identity}")
def edit(identity: int, body: FlowInput, access: Access):
    return flows.save(access, body, identity)


@router.delete("/flows/{identity}")
def delete(identity: int, access: Access):
    return flows.delete(access, identity)


@router.post("/flows/{identity}/enabled")
def enable(identity: int, body: EnableInput, access: Access):
    return flows.set_enabled(access, identity, body)


@router.get("/flows/{identity}/runs")
def flow_runs(identity: int, access: Access):
    return flows.runs(access, flow_id=identity)


@router.get("/flow-runs")
def runs(access: Access, brand_id: int | None = None, status: str | None = None):
    return flows.runs(access, brand_id=brand_id, status=status)


@router.get("/flow-runs/{identity}")
def run_detail(identity: int, access: Access):
    return flows.run_detail(access, identity)


@router.post("/flow-runs/{identity}/approve")
def approve(identity: int, body: ApproveInput, request: Request, access: Access):
    return flows.approve(access, request.app.state.settings, identity, body)


@router.post("/flow-runs/{identity}/cancel")
def cancel(identity: int, access: Access):
    return flows.cancel_run(access, identity)
