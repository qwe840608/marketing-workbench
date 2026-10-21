
from fastapi import APIRouter, Request

from app.api.dependencies import Access
from app.schemas.classify import IntentNotesUpdate
from app.services import classify

router = APIRouter(prefix="/api/classifications")


@router.get("/intents")
def get_intents(brand_id: int, access: Access):
    return classify.intent_notes_view(access, brand_id)


@router.put("/intents")
def set_intents(brand_id: int, body: IntentNotesUpdate, access: Access):
    return classify.update_intent_notes(access, body, brand_id)


@router.get("/messages/{message_id}")
def get_classification(message_id: int, access: Access):
    return classify.view(access, message_id)


@router.post("/messages/{message_id}")
def classify_message(message_id: int, request: Request, access: Access):
    return classify.manual(
        access, request.app.state.session_factory, request.app.state.settings, message_id
    )
