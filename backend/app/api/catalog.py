from datetime import date
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query, Request

from app.api.dependencies import Access
from app.models import Account, Brand, Contact, Post, Thread
from app.schemas.catalog import (
    AccountView,
    BrandView,
    ContactView,
    MessageView,
    MetricView,
    PostView,
    ThreadView,
)
from app.schemas.followers import FollowerQuery
from app.schemas.posts import MetaPlatform, PostPlatform
from app.services import (
    catalog,
    comment_backfill,
    comment_poll,
    followers,
    post_comment_pages,
    post_thumbnails,
)
from app.services import posts as post_service
from app.services.date_ranges import DatePeriod

router = APIRouter(prefix="/api")
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]
BrandFilter = Annotated[int | None, Query(ge=1)]


@router.get("/brands", response_model=list[BrandView])
def brands(access: Access, limit: Limit = 100, offset: Offset = 0):
    return catalog.list_records(access, Brand, None, limit, offset)


@router.get("/accounts", response_model=list[AccountView])
def accounts(access: Access, brand_id: BrandFilter = None, limit: Limit = 100, offset: Offset = 0):
    return catalog.list_records(access, Account, brand_id, limit, offset)


@router.get("/contacts", response_model=list[ContactView])
def contacts(access: Access, brand_id: BrandFilter = None, limit: Limit = 100, offset: Offset = 0):
    return catalog.list_records(access, Contact, brand_id, limit, offset)


@router.get("/contacts/{contact_id}", response_model=ContactView)
def contact(contact_id: int, access: Access):
    return catalog.get_record(access, Contact, contact_id)


@router.get("/threads", response_model=list[ThreadView])
def threads(access: Access, brand_id: BrandFilter = None, limit: Limit = 100, offset: Offset = 0):
    return catalog.list_records(access, Thread, brand_id, limit, offset)


@router.get("/threads/{thread_id}", response_model=ThreadView)
def thread(thread_id: int, access: Access):
    return catalog.get_record(access, Thread, thread_id)


@router.get("/threads/{thread_id}/messages", response_model=list[MessageView])
def messages(thread_id: int, access: Access, limit: Limit = 100, offset: Offset = 0):
    return catalog.thread_messages(access, thread_id, limit, offset)


@router.get("/posts", response_model=list[PostView])
def posts(
    access: Access,
    brand_id: BrandFilter = None,
    limit: Limit = 100,
    offset: Offset = 0,
    platform: PostPlatform | None = None,
    period: DatePeriod = "all",
    date_from: date | None = None,
    date_to: date | None = None,
):
    return post_service.list_posts(
        access, brand_id, limit, offset, platform, period, date_from, date_to
    )


@router.get("/posts/platforms")
def post_platforms(request: Request, access: Access, brand_id: BrandFilter = None):
    return post_service.platforms(access, brand_id, request.app.state.settings)


@router.get("/posts/followers")
def follower_counts(
    access: Access,
    filters: Annotated[FollowerQuery, Query()],
):
    return followers.view(access, **filters.model_dump())


@router.get("/posts/comments/backfill")
def backfill_status(
    access: Access,
    request: Request,
    brand_id: BrandFilter = None,
    platform: MetaPlatform | None = None,
):
    return comment_backfill.status(access, brand_id, platform, request.app.state.settings)


@router.post("/posts/comments/backfill", status_code=202)
def start_backfill(
    access: Access,
    request: Request,
    tasks: BackgroundTasks,
    brand_id: BrandFilter = None,
    platform: MetaPlatform | None = None,
):
    result = comment_backfill.start(access, brand_id, platform, settings=request.app.state.settings)
    if result["created"]:
        tasks.add_task(comment_poll.wake, request.app.state.settings)
    return result


@router.get("/posts/{post_id}/comments")
def post_comments(post_id: int, access: Access, limit: Limit = 200, after_id: Offset = 0):
    return post_service.comments(access, post_id, limit, after_id)


@router.get("/posts/{post_id}/comment-threads")
def post_comment_threads(
    post_id: int,
    access: Access,
    limit: Limit = 50,
    offset: Offset = 0,
    period: DatePeriod = "all",
    date_from: date | None = None,
    date_to: date | None = None,
    focus_id: Annotated[int | None, Query(ge=1)] = None,
):
    return post_comment_pages.comment_page(
        access, post_id, limit, offset, period, date_from, date_to, focus_id
    )


@router.get("/posts/{post_id}", response_model=PostView)
def post(post_id: int, access: Access):
    return catalog.get_record(access, Post, post_id)


@router.get("/posts/{post_id}/thumbnail")
def post_thumbnail(post_id: int, access: Access):
    return post_thumbnails.image(access, post_id)


@router.get("/posts/{post_id}/metrics", response_model=list[MetricView])
def metrics(post_id: int, access: Access, limit: Limit = 100, offset: Offset = 0):
    return catalog.post_metrics(access, post_id, limit, offset)


@router.get("/posts/{post_id}/comments/sync")
def comment_status(post_id: int, access: Access, request: Request):
    return comment_poll.status(access, post_id, request.app.state.settings)


@router.post("/posts/{post_id}/comments/sync", status_code=202)
def sync_post_comments(post_id: int, access: Access, request: Request, tasks: BackgroundTasks,
                       period: DatePeriod = "30", date_from: date | None = None,
                       date_to: date | None = None, full_rescan: bool = False):
    result = comment_poll.request_sync(
        access, post_id=post_id, settings=request.app.state.settings,
        period=period, date_from=date_from, date_to=date_to, full_rescan=full_rescan,
    )
    if result["queued"]:
        tasks.add_task(comment_poll.wake, request.app.state.settings, post_id)
    return result


@router.post("/posts/{post_id}/comments/stop")
def stop_post_comments(post_id: int, access: Access):
    return comment_poll.stop(access, post_id)


@router.post("/posts/comments/sync", status_code=202)
def sync_recent_comments(
    access: Access,
    request: Request,
    tasks: BackgroundTasks,
    brand_id: BrandFilter = None,
    platform: MetaPlatform | None = None,
):
    result = comment_poll.request_sync(
        access, brand_id=brand_id, platform=platform, settings=request.app.state.settings
    )
    if result["queued"]:
        tasks.add_task(comment_poll.wake, request.app.state.settings)
    return result
