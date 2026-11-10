from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime, Versioned


class PublishFlow(Base, Versioned):
    """使用者拉出的發文流程；方塊與連線存在 graph_json，送出仍交給既有發佈。"""

    __tablename__ = "publish_flows"
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    creator_id: Mapped[int] = mapped_column(ForeignKey("staff.id"))
    name: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    graph_json: Mapped[dict] = mapped_column(JSON, default=dict)
    next_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class PublishFlowRun(Base):
    """一次執行。觸發當下凍結流程內容，之後改流程不影響進行中的執行。"""

    __tablename__ = "publish_flow_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running','awaiting_approval','scheduled','done','partial','failed',"
            "'expired','cancelled','missed')",
            name="status",
        ),
    )
    flow_id: Mapped[int] = mapped_column(ForeignKey("publish_flows.id"), index=True)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    trigger_at: Mapped[datetime] = mapped_column(UTCDateTime())
    graph_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    # 下一個要處理的方塊；None 代表走完。
    current_node: Mapped[str | None] = mapped_column(String(40))
    draft_post_id: Mapped[int | None] = mapped_column(ForeignKey("publish_posts.id"))
    wake_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    approval_deadline: Mapped[datetime | None] = mapped_column(UTCDateTime())
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    approved_by: Mapped[int | None] = mapped_column(Integer)
    steps_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(200))
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
