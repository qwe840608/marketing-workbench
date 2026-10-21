"""Origin-independent evidence identity, also for legacy report snapshots."""

from app.models import Message, Thread


def quote_identity(session, quote, brand_id):
    result = {key: value for key, value in quote.items() if key != "url"}
    message = session.get(Message, quote.get("id"))
    thread = session.get(Thread, message.thread_id) if message else None
    if thread and thread.brand_id == brand_id:
        result.update(kind=thread.kind, thread_id=thread.id, post_id=thread.post_id)
    else:
        result.update(kind=None, thread_id=None, post_id=None)
    return result


def quote_path(quote, brand_id, report_id):
    base = f"/?brand_id={brand_id}&return_report_id={report_id}"
    if quote.get("kind") == "comment_thread" and quote.get("post_id"):
        return base + f"&view=posts&post_id={quote['post_id']}&comment_id={quote['id']}"
    if quote.get("kind") == "dm" and quote.get("thread_id"):
        return base + f"&thread_id={quote['thread_id']}&message_id={quote['id']}"
    return f"/?view=ideation&brand_id={brand_id}&report_id={report_id}"
