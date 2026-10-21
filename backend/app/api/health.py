from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.services.health import database_health

router = APIRouter(prefix="/api")


@router.get("/health")
def health(session: Annotated[Session, Depends(get_session)]) -> dict:
    return database_health(session)
