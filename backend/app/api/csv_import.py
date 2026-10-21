from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import Access
from app.schemas.csv_import import Confirm, Mapping, Upload
from app.services import csv_import

router = APIRouter(prefix="/api/csv")


async def body(request, model):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 3 * 1024 * 1024:
            raise HTTPException(413, "上傳請求超過大小限制")
    try:
        return model.model_validate_json(bytes(data))
    except ValidationError:
        raise HTTPException(422, "匯入請求格式無效") from None


@router.get("/accounts")
def accounts(brand_id: int, access: Access):
    return csv_import.accounts(access, brand_id)


@router.post("/preview")
async def preview(request: Request, access: Access):
    data = await body(request, Upload)
    return await run_in_threadpool(
        csv_import.upload,
        access,
        data,
        request.app.state.settings,
        request.app.state.csv_import_store,
    )


@router.post("/validate")
async def validate(request: Request, access: Access):
    data = await body(request, Mapping)
    return await run_in_threadpool(
        csv_import.validate, access, data, request.app.state.csv_import_store
    )


@router.post("/confirm")
async def confirm(request: Request, access: Access):
    data = await body(request, Confirm)
    return await run_in_threadpool(
        csv_import.confirm, access, data, request.app.state.csv_import_store
    )
