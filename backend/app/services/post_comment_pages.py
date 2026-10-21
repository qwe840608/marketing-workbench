"""Page complete comment trees without loading unselected message bodies."""

from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import and_, func, select

from app.models import Account, Contact, Message, Post, Thread
from app.services.catalog import get_record
from app.services.date_ranges import filter_dates
from app.services.message_content import message_view


def comment_page(
    access, post_id, limit=50, offset=0, period="all", date_from=None, date_to=None, focus_id=None
):
    post = get_record(access, Post, post_id)
    query = access.statement(Message).where(
        Thread.post_id == post.id,
        Thread.account_id == post.account_id,
        Thread.kind == "comment_thread",
    )
    total = access.session.scalar(select(func.count()).select_from(query.subquery()))
    filtered = filter_dates(query, Message.sent_at, period, date_from, date_to)
    # Only relationship metadata is needed to handle legacy missing/ambiguous/cyclic parents.
    # Message bodies and attachments are fetched only for the selected page.
    metadata = access.session.execute(
        filtered.with_only_columns(
            Message.id,
            Message.external_id,
            Message.comment_parent_known,
            Message.comment_parent_id,
            Message.comment_root_id,
        )
    ).all()
    range_total = len(metadata)
    ambiguous = set(
        access.session.scalars(
            query.with_only_columns(Message.external_id)
            .group_by(Message.external_id)
            .having(func.count() > 1)
        )
    )
    roots = _roots(metadata, ambiguous)
    focus_group = []
    if focus_id is not None and focus_id not in roots:
        # A report link reads an already stored tree, independently of display dates.
        # Keep normal range counts and offsets so subsequent pages have no gaps.
        all_metadata = access.session.execute(
            query.with_only_columns(
                Message.id, Message.external_id, Message.comment_parent_known,
                Message.comment_parent_id, Message.comment_root_id,
            )
        ).all()
        all_roots = _roots(all_metadata, ambiguous)
        if focus_id not in all_roots:
            raise HTTPException(404, "此貼文找不到指定留言")
        focus_root = all_roots[focus_id]
        focus_group = [node for node, root in all_roots.items() if root == focus_root]
    root_ids = set(roots.values())
    if focus_id is not None and not focus_group:
        ordered = list(
            access.session.scalars(
                filtered.with_only_columns(Message.id)
                .where(Message.id.in_(root_ids))
                .order_by(Message.sent_at.desc(), Message.id.desc())
            )
        )
        offset = (ordered.index(roots[focus_id]) // limit) * limit
    page_roots = list(
        access.session.scalars(
            filtered.with_only_columns(Message.id)
            .where(Message.id.in_(root_ids))
            .order_by(Message.sent_at.desc(), Message.id.desc())
            .limit(limit + 1)
            .offset(offset)
        )
    )
    selected_roots = set(page_roots[:limit])
    selected_ids = [node for node, root in roots.items() if root in selected_roots]
    visible_roots = page_roots[:limit]
    if focus_group:
        selected_ids = list(set(selected_ids) | set(focus_group))
        visible_roots = [focus_root, *[root for root in visible_roots if root not in focus_group]]
    rows = access.session.execute(
        query.where(Message.id.in_(selected_ids))
        .outerjoin(
            Contact,
            and_(
                func.coalesce(Message.contact_id, Thread.contact_id) == Contact.id,
                Contact.brand_id == Thread.brand_id,
            ),
        )
        .add_columns(Contact.display_name)
        .order_by(Message.sent_at, Message.id)
    ).all()
    items = [message_view(message, name) for message, name in rows]
    if access.session.get(Account, post.account_id).platform == "youtube":
        from app.services.redact import redact

        items = [item.model_copy(update={
            "text": redact(item.text).text,
            "contact_name": "品牌" if item.author_type == "brand" else f"觀眾{item.contact_id}",
        }) for item in items]
    return {
        "items": items,
        "total": total,
        "range_total": range_total,
        "root_total": len(root_ids),
        "root_ids": visible_roots,
        "next_offset": offset + limit if len(page_roots) > limit else None,
    }


def _roots(metadata, ambiguous):
    by_external = defaultdict(list)
    for row in metadata:
        by_external[row.external_id].append(row.id)
    parents = {}
    missing_groups = defaultdict(list)
    for row in metadata:
        candidates = by_external[row.comment_parent_id]
        if (
            row.comment_parent_known
            and len(candidates) == 1
            and row.comment_parent_id not in ambiguous
        ):
            parents[row.id] = candidates[0]
        elif row.comment_parent_known and row.comment_parent_id and not candidates:
            missing_groups[row.comment_root_id or row.comment_parent_id].append(row.id)

    # An old/missing parent still identifies one group. Use a visible reply as the
    # representative, without loading or inventing the parent's body.
    for external, siblings in missing_groups.items():
        if external not in ambiguous:
            representative = max(siblings)
            for sibling in siblings:
                if sibling != representative:
                    parents[sibling] = representative

    roots = {}
    for row in metadata:
        chain, positions = [], {}
        current = row.id
        while current not in roots and current not in positions:
            positions[current] = len(chain)
            chain.append(current)
            if current not in parents:
                roots[current] = current
                break
            current = parents[current]
        if current in positions and current not in roots:
            # Break each cyclic edge; never invent a parent for corrupt platform data.
            for cyclic in chain[positions[current] :]:
                roots[cyclic] = cyclic
                parents.pop(cyclic, None)
        for node in reversed(chain):
            if node not in roots:
                roots[node] = roots[parents[node]]

    return roots
