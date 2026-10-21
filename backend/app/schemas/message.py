from datetime import datetime

from app.schemas.catalog import MessageView


class MessageContent(MessageView):
    contact_name: str
    attachments_json: list[dict]
    received_at: datetime
    has_text: bool
