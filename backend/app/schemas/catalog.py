from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class RecordView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int


class BrandView(RecordView):
    slug: str
    name: str
    version: int


class AccountView(RecordView):
    brand_id: int
    platform: str
    external_id: str
    name: str
    status: str


class ContactView(RecordView):
    brand_id: int
    platform: str
    external_id: str
    display_name: str


class ThreadView(RecordView):
    brand_id: int
    account_id: int
    kind: str
    contact_id: int | None
    post_id: int | None
    source_ref_json: dict
    owner_staff_id: int | None
    owner_person_id: int | None
    assignment_mode: str
    status: str
    stage: str
    list_color: str | None
    booking_date: date | None
    booking_units: int | None
    last_inbound_at: datetime | None
    last_outbound_at: datetime | None
    version: int


class MessageView(RecordView):
    contact_id: int | None
    thread_id: int
    external_id: str
    comment_parent_id: str | None
    comment_root_id: str | None
    comment_parent_known: bool
    direction: str
    sent_by_staff_id: int | None
    sender_name: str | None
    author_type: str
    text: str
    sent_at: datetime
    edited_at: datetime | None
    sources_json: list[str]
    version: int


class PostView(RecordView):
    account_id: int
    external_id: str
    permalink: str | None
    caption: str
    media_type: str
    visibility: str | None = None
    published_at: datetime
    schedule_tier: str
    thumbnail_url: str | None = None


class MetricView(RecordView):
    post_id: int
    captured_at: datetime
    views: int | None
    reach: int | None
    likes: int | None
    comments: int | None
    shares: int | None
    saves: int | None
    avg_watch_time: Decimal | None
    completion_rate: Decimal | None
    extra_json: dict
