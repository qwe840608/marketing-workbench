"""Meta／Threads／YouTube 留言的單篇一次性讀取（使用者按「抓取留言」建立的工作）。"""

import copy
import logging

from app.logging_config import log_failure
from app.schemas import meta as schemas
from app.schemas.posts import PostsInput
from app.services import comment_poll, posts
from app.services.webhook_normalize import digest, instant, valid_id
from app.services.workers.base import WorkerError

logger = logging.getLogger("mwb.gateway_workers")
THREADS_REPLY_FIELDS = "id,text,timestamp,username,replied_to,is_reply_owned_by_me"


class RequestBudget:
    """單次留言 worker 的平台請求預算：最多 35 次、50 秒。"""

    def __init__(self, clock):
        self.clock, self.started, self.requests = clock, clock(), 0

    def available(self):
        return self.requests < 35 and self.clock() - self.started < 50

    def spend(self):
        self.requests += 1


class CommentRun:
    """一份已領取的留言工作：進度、已知留言 ID 與本次新增計數。"""

    def __init__(self, work, platform, account):
        self.work, self.platform, self.account = work, platform, account
        self.progress = {
            "after": None,
            "comments_done": False,
            "replies": [],
            "pages": 0,
            "saved_comments": 0,
            **copy.deepcopy(work.get("progress") or {}),
        }
        self.known = set(work.get("known_comment_ids", []))

    def done(self):
        return self.progress["comments_done"] and not self.progress["replies"]

    def stored_page(self, rows):
        # 格式不符的列不算「已存」，交由既有解析流程處理，不提前停止。
        return bool(self.work.get("incremental") and isinstance(rows, list) and rows
                    and all(isinstance(row, dict) and row.get("id") in self.known
                            for row in rows))

    def count_new(self, rows):
        work, progress, known = self.work, self.progress, self.known
        start, end = instant(work.get("window_start")), instant(work.get("window_end"))
        ids = set()
        for row in rows if isinstance(rows, list) else []:
            # 只做計數；缺欄位或非物件的列略過，不可讓整頁同步失敗。
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                continue
            stamp = instant(row.get("created_time" if self.platform == "facebook"
                                    else "timestamp"))
            in_window = (start is None or stamp and start <= stamp)
            if stamp and in_window and (end is None or stamp < end):
                ids.add(row["id"])
        progress["new_comments"] = progress.get("new_comments", 0) + len(ids - known)
        known.update(ids)


class CommentsMixin:
    def page(self, work, platform, account, resource, edge, after):
        discovery = edge in ("media", "published_posts")
        facebook = platform == "facebook"
        fields = (
            (
                "id,message,permalink_url,created_time,attachments{media_type}"
                if facebook
                else "id,caption,media_type,media_product_type,permalink,timestamp"
            )
            if discovery
            else (
                "id,message,created_time,from{id,name},parent{id}"
                if facebook
                else "id,text,timestamp,from{id,username}"
            )
        )
        if not discovery and resource == work["resource_id"]:
            nested = "comments" if facebook else "replies"
            if facebook:
                nested += ".filter(stream).order(reverse_chronological)"
            fields += "," + nested + ".limit(50){" + fields + "}"
        query = dict(fields=fields, limit=50)
        if facebook and not discovery:
            query.update(
                filter="toplevel" if resource == work["resource_id"] else "stream",
                order="reverse_chronological",
            )
        if after:
            query["after"] = after
        response = self.graph(
            resource + "/" + edge,
            query,
            dict(
                source="poll",
                platform=platform,
                account_external_id=account,
                run_id=work["run_id"],
            ),
        )
        data = response.get("body") or {}
        if response["statusCode"] != 200 or data.get("error"):
            error = data.get("error") or {}
            code = error.get("code")
            name = (
                "meta_rate_limited"
                if response["statusCode"] == 429 or code in (4, 17, 32, 613, 80004)
                else "meta_auth_error"
                if code == 190
                else "meta_api_error"
            )
            raise WorkerError(name)
        if not isinstance(data.get("data"), list) or len(data["data"]) > 50:
            raise WorkerError("invalid_response")
        paging = data.get("paging") or {}
        cursor = (paging.get("cursors") or {}).get("after") if paging.get("next") else None
        if paging.get("next") and (
            not isinstance(cursor, str) or not cursor or len(cursor) > 4096 or cursor == after
        ):
            raise WorkerError("invalid_pagination")
        return {**response, "next": cursor}

    def save_comments(self, work, page, parent, platform, account):
        rows = page["body"]["data"]
        facebook = platform == "facebook"
        if work.get("window_end"):
            start, end = instant(work["window_start"]), instant(work["window_end"])
            filtered = []
            for row in rows:
                stamp = instant(row.get("created_time" if facebook else "timestamp"))
                if not stamp:
                    raise WorkerError("invalid_response")
                if (start is None or start <= stamp) and stamp < end:
                    filtered.append(row)
            rows = filtered
        if not rows:
            return 0
        # Keep out-of-window nested bodies out of raw-event storage too.
        rows = [{k: v for k, v in row.items() if k not in {"replies", "comments"}} for row in rows]
        messages = []
        try:
            for row in rows:
                author = row.get("from") or {}
                text = row.get("message", "") if facebook else row.get("text")
                stamp = instant(row.get("created_time" if facebook else "timestamp"))
                if (
                    not valid_id(row.get("id"))
                    or not valid_id(author.get("id"))
                    or not isinstance(text, str)
                    or not stamp
                ):
                    raise ValueError()
                direct = (
                    (row.get("parent") or {}).get("id", parent) if facebook and parent else parent
                )
                known = not parent or not facebook or valid_id(direct)
                own = author["id"] == account
                name = author.get("username") or author.get("name")
                messages.append(
                    dict(
                        external_id=row["id"],
                        thread_external_id=work["resource_id"],
                        kind="comment_thread",
                        post_external_id=work["resource_id"],
                        contact={
                            "external_id": author["id"],
                            **({"display_name": name} if name else {}),
                        },
                        direction="out" if own else "in",
                        author_type="brand" if own else "fan",
                        text=text,
                        sent_at=stamp,
                        source_ref_json=dict(
                            post_external_id=work["resource_id"],
                            parent_known=bool(known),
                            parent_id=direct or None,
                            root_id=(parent or row["id"]) if known else None,
                        ),
                    )
                )
        except (ValueError, KeyError, TypeError):
            messages = None
        payload = {
            "edge": parent + ("/comments" if facebook else "/replies")
            if parent
            else work["resource_id"] + "/comments",
            "data": rows,
        }
        body = dict(
            platform=platform,
            account_external_id=account,
            external_id="poll:" + digest(payload),
            source="poll",
            signature_ok=False,
            poll_run_id=work["run_id"],
            poll_call_id=page["call_id"],
            payload=payload,
            messages=messages,
        )
        if "observed_at" in page:
            body["observed_at"] = page["observed_at"]
        self.save_poll_events(body)
        return len(rows)

    def threads_replies(self, work, after):
        found = self.threads_account()
        if not found:
            raise WorkerError("meta_auth_error")
        if self.threads_access() == "missing":
            logger.info(
                "threads_data_skipped",
                extra={"reason": "permission_missing", "operation": "replies"},
            )
            raise WorkerError("threads_permission_missing")
        try:
            return self.threads_edge(
                work["resource_id"] + "/conversation",
                dict(fields=THREADS_REPLY_FIELDS, reverse="true", limit=50),
                found[1],
                after,
                "invalid_response",
            )
        except WorkerError as error:
            if error.code == "threads_permission_missing":
                self.threads_block()
            raise

    def save_threads_replies(self, work, rows, account, platform="threads"):
        post = work["resource_id"]
        if work.get("window_end"):
            start, end = instant(work["window_start"]), instant(work["window_end"])
            kept = []
            for row in rows:
                stamp = instant(row.get("timestamp"))
                if not stamp:
                    raise WorkerError("invalid_response")
                if (start is None or start <= stamp) and stamp < end:
                    kept.append(row)
            rows = kept
        if not rows:
            return 0
        messages = []
        try:
            for row in rows:
                identity, stamp = row.get("id"), instant(row.get("timestamp"))
                text = row.get("text")
                if not valid_id(identity) or not stamp:
                    raise ValueError()
                if text is not None and not isinstance(text, str):
                    raise ValueError()
                parent = (row.get("replied_to") or {}).get("id")
                known = valid_id(parent)
                top = known and parent == post
                own = row.get("is_reply_owned_by_me") is True
                name = row.get("username") if isinstance(row.get("username"), str) else None
                # 回覆沒有作者編號：自己的回覆用帳號編號，其他人用使用者名稱，缺名稱時每則獨立。
                author = account if own else (row.get("author_id") or name or "unknown:" + identity)
                messages.append(
                    dict(
                        external_id=identity,
                        thread_external_id=post,
                        kind="comment_thread",
                        post_external_id=post,
                        contact={"external_id": author, **({"display_name": name} if name else {})},
                        direction="out" if own else "in",
                        author_type="brand" if own else "fan",
                        text=text or "",
                        sent_at=stamp,
                        source_ref_json=dict(
                            post_external_id=post,
                            parent_known=bool(known),
                            parent_id=parent if known and not top else None,
                            root_id=identity if top else None,
                        ),
                    )
                )
        except (ValueError, KeyError, TypeError):
            messages = None
        payload = {"edge": post + "/conversation", "data": rows}
        body = dict(
            platform=platform,
            account_external_id=account,
            external_id="poll:" + digest(payload),
            source="poll",
            signature_ok=False,
            poll_run_id=work["run_id"],
            payload=payload,
            messages=messages,
        )
        self.save_poll_events(body)
        return len(rows)

    @staticmethod
    def older_page(work, rows, platform):
        start = instant(work.get("window_start"))
        if not start or not rows:
            return False
        stamps = [instant(row.get("created_time" if platform == "facebook" else "timestamp"))
                  for row in rows]
        if any(stamp is None for stamp in stamps):
            raise WorkerError("invalid_response")
        return all(stamp < start for stamp in stamps)

    @staticmethod
    def nested_replies(row, facebook):
        edge = row.get("comments" if facebook else "replies")
        if edge is None:
            # Meta omits an expanded edge with no visible replies. Verified with GET;
            # never turn this into one additional request per comment.
            return [], None
        if (
            not isinstance(edge, dict)
            or not isinstance(edge.get("data"), list)
            or len(edge["data"]) > 50
        ):
            raise WorkerError("invalid_response")
        paging = edge.get("paging") or {}
        after = (paging.get("cursors") or {}).get("after") if paging.get("next") else None
        if paging.get("next") and (not isinstance(after, str) or not after or len(after) > 4096):
            raise WorkerError("invalid_pagination")
        return edge["data"], after

    def comments(self, requested_only=False, post_id=None):
        """依序輪流各帳號領取一次性留言工作，在本輪 35 次請求／50 秒預算內讀頁並存檔。"""
        if hasattr(self, "_youtube_comments"):
            del self._youtube_comments
        accounts = self.accounts(True)
        budget = RequestBudget(self.clock)
        empty = 0
        index = 0
        result = dict(ok=True, completed=0, paused=False)
        while budget.available() and empty < len(accounts):
            platform, account = accounts[index % len(accounts)]
            index += 1
            run = None
            try:
                claim = self.claim_comment_work(platform, account, requested_only, post_id)
                work = claim.get("work")
                if not work:
                    empty += 1
                    if claim.get("retry_at"):
                        result["paused"] = True
                        break
                    continue
                empty = 0
                run = CommentRun(work, platform, account)
                while budget.available() and not run.done():
                    budget.spend()
                    self.read_comment_page(run)
                    run.progress["pages"] += 1
                    self.checkpoint_comment_work(run)
                done = run.done()
                self.finish_comment_work(
                    run, success=bool(done), error=None if done else "work_budget"
                )
                if done:
                    result["completed"] += 1
                else:
                    result["paused"] = True
                    break
            except Exception as error:
                log_failure("mwb.gateway_workers", "gateway_workers_comments_failed", error)
                code = error.code if isinstance(error, WorkerError) else "invalid_response"
                if run:
                    try:
                        self.finish_comment_work(run, success=False, error=code)
                    except Exception as error:
                        log_failure("mwb.gateway_workers", "gateway_workers_comments_failed", error)
                result.update(ok=code == "meta_rate_limited", paused=True, error=code)
                break
        return result

    def claim_comment_work(self, platform, account, requested_only, post_id):
        return self.service(
            comment_poll.claim,
            schemas.PollClaim.model_validate(
                dict(
                    platform=platform,
                    account_external_id=account,
                    requested_only=requested_only,
                    post_id=post_id,
                )
            ),
            self.settings,
        )

    def checkpoint_comment_work(self, run):
        self.service(
            comment_poll.checkpoint,
            schemas.PollCheckpoint.model_validate(
                dict(run_id=run.work["run_id"], progress=run.progress)
            ),
        )

    def finish_comment_work(self, run, *, success, error):
        self.service(
            comment_poll.finish,
            schemas.PollFinish.model_validate(
                dict(run_id=run.work["run_id"], progress=run.progress, success=success, error=error)
            ),
            self.settings,
        )

    def read_comment_page(self, run):
        """讀一頁並更新進度；依平台與工作階段（貼文清單、回覆續頁、主留言）分派。"""
        if run.platform == "youtube":
            self.youtube_comment_page(run)
        elif run.platform == "threads":
            self.threads_comment_page(run)
        elif run.work["kind"] == "media":
            self.media_page(run)
        elif run.progress["replies"]:
            self.reply_page(run)
        else:
            self.top_comment_page(run)

    def youtube_comment_page(self, run):
        work, progress, account = run.work, run.progress, run.account
        if not hasattr(self, "_youtube_comments"):
            self._youtube_comments = self.youtube_sync()
        reader = self._youtube_comments
        rows, cursor, pending = reader.comments_page(work, progress)
        normalized = [{**row,
            "replied_to": {"id": row.get("parent_id") or work["resource_id"]},
            "is_reply_owned_by_me": row["author_id"] == account,
        } for row in rows]
        progress["saved_comments"] += self.save_threads_replies(
            work, normalized, account, "youtube")
        run.count_new(normalized)
        # Only top-level pages are time ordered; replies have no documented order.
        if pending is None:
            if cursor:
                progress["replies"][0]["after"] = cursor
            else:
                progress["replies"].pop(0)
        else:
            progress.update(after=cursor, comments_done=not cursor, replies=pending)

    def threads_comment_page(self, run):
        work, progress = run.work, run.progress
        # conversation 一次攤平所有層級，每則附 replied_to，不需逐則補查巢狀回覆。
        rows, cursor = self.threads_replies(work, progress["after"])
        existing = run.stored_page(rows)
        progress["saved_comments"] += self.save_threads_replies(work, rows, run.account)
        run.count_new(rows)
        if existing or self.older_page(work, rows, run.platform):
            cursor = None
        progress.update(after=cursor, comments_done=not cursor)

    def media_page(self, run):
        work, progress, platform, account = run.work, run.progress, run.platform, run.account
        page = self.page(
            work,
            platform,
            account,
            work["resource_id"],
            "published_posts" if platform == "facebook" else "media",
            progress["after"],
        )
        rows = page["body"]["data"]
        if work.get("window_end"):
            filtered = []
            for row in rows:
                stamp = instant(row.get("created_time") or row.get("timestamp"))
                if not stamp:
                    raise WorkerError("invalid_response")
                if stamp <= instant(work["window_end"]):
                    filtered.append(row)
            rows = filtered
        if rows:
            self.service(
                posts.upsert_posts,
                PostsInput.model_validate(
                    dict(
                        platform=platform,
                        account_external_id=account,
                        posts=[self.post(p) for p in rows],
                    )
                ),
            )
        progress.update(after=page["next"], comments_done=not page["next"])

    def reply_page(self, run):
        work, progress, platform, account = run.work, run.progress, run.platform, run.account
        parent = progress["replies"][0]
        page = self.page(
            work,
            platform,
            account,
            parent["id"],
            "comments" if platform == "facebook" else "replies",
            parent.get("after"),
        )
        existing = run.stored_page(page["body"]["data"])
        progress["saved_comments"] += self.save_comments(
            work, page, parent["id"], platform, account
        )
        run.count_new(page["body"]["data"])
        if existing or self.older_page(work, page["body"]["data"], platform):
            page["next"] = None
        if page["next"]:
            parent["after"] = page["next"]
        else:
            progress["replies"].pop(0)

    def top_comment_page(self, run):
        work, progress, platform, account = run.work, run.progress, run.platform, run.account
        page = self.page(
            work,
            platform,
            account,
            work["resource_id"],
            "comments",
            progress["after"],
        )
        # Validate all nested pages before checkpointing the top-level cursor.
        nested = [
            (row, *self.nested_replies(row, platform == "facebook"))
            for row in page["body"]["data"]
        ]
        existing = run.stored_page(page["body"]["data"])
        progress["saved_comments"] += self.save_comments(work, page, None, platform, account)
        pending = []
        run.count_new(page["body"]["data"])
        for row, replies, after in nested:
            existing_replies = run.stored_page(replies)
            progress["saved_comments"] += self.save_comments(
                work,
                {**page, "body": {"data": replies}},
                row["id"],
                platform,
                account,
            )
            run.count_new(replies)
            if (after and not existing_replies
                    and not self.older_page(work, replies, platform)):
                pending.append({"id": row["id"], "after": after})
        if existing or self.older_page(work, page["body"]["data"], platform):
            page["next"] = None
        progress.update(replies=pending, after=page["next"], comments_done=not page["next"])
