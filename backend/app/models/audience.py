from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UTCDateTime


class AudienceInsight(Base):
    """各帳號受眾分布的最新一份（年齡、性別、地區、上線時段）；每日覆寫，不保留歷史。"""

    __tablename__ = "audience_insights"
    __table_args__ = (UniqueConstraint("account_id", "metric", "breakdown"),)

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    # followers＝追蹤者分布；viewers＝觀眾分布（YouTube）；online＝追蹤者上線時段（IG）。
    metric: Mapped[str] = mapped_column(String(16))
    # age／gender／age_gender／country／city／hour
    breakdown: Mapped[str] = mapped_column(String(16))
    # ready＝有資料；unavailable＝平台沒有回資料或不提供，error 記代碼供介面提示。
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(String(40))
    # 平台統計的期間（this_month、last_28_days、last_7_days、lifetime）。
    period: Mapped[str] = mapped_column(String(32))
    # [{"key": "25-34", "value": 123}, ...]；value 是人數或百分比，依 unit 而定。
    items_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    unit: Mapped[str] = mapped_column(String(16), default="count")
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime())
