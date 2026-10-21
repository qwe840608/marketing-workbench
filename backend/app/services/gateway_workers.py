"""Native workers; all database operations call the existing services directly.

Workers 由各職責模組組合；此處保留原本的匯入路徑與常數供排程、YouTube 與測試使用。
"""

from app.services.workers.audience import AudienceMixin
from app.services.workers.base import WorkerBase, WorkerError, usage_headers
from app.services.workers.comments import THREADS_REPLY_FIELDS, CommentsMixin
from app.services.workers.followers import FollowersMixin
from app.services.workers.metrics import (
    THREADS_INSIGHT_LIMIT,
    THREADS_METRICS,
    THREADS_PAGE_LIMIT,
    THREADS_POST_FIELDS,
    MetricsMixin,
    insight_value,
    metric_count,
)
from app.services.workers.notify import NotifyMixin

__all__ = [
    "THREADS_INSIGHT_LIMIT",
    "THREADS_METRICS",
    "THREADS_PAGE_LIMIT",
    "THREADS_POST_FIELDS",
    "THREADS_REPLY_FIELDS",
    "WorkerError",
    "Workers",
    "insight_value",
    "metric_count",
    "usage_headers",
]


class Workers(AudienceMixin, CommentsMixin, FollowersMixin, MetricsMixin, NotifyMixin, WorkerBase):
    """排程使用的 worker：留言、粉絲數、受眾、成效與通知共用同一組平台／service 呼叫。"""
