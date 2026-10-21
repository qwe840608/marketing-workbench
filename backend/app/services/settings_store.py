"""Setting 表的共用讀寫與版本化設定的樂觀鎖檢查。

各設定的鍵名、預設值、稽核內容與 409 文案仍由各自的服務決定；這裡只收斂重複的查詢與
新增／更新寫法，行為與原本逐處手寫相同。
"""

from fastapi import HTTPException
from sqlalchemy import select

from app.models import Setting


def get(session, key):
    """回傳該鍵的 Setting 列；不存在時為 None。"""
    return session.scalar(select(Setting).where(Setting.key == key))


def version(row):
    """尚未建立的設定視為版本 0，與前端第一次儲存時送出的版本一致。"""
    return row.version if row else 0


def require_version(row, expected, message="設定已更新，請重新整理"):
    """畫面送來的版本與資料庫不同時回 409，避免覆蓋別人剛存的設定。"""
    if version(row) != expected:
        raise HTTPException(409, message)


def put(session, key, value, row):
    """以先前讀到的 row（可為 None）寫入新值；不存在就新增。回傳寫入的列。"""
    if row is None:
        row = Setting(key=key, value_json=value)
        session.add(row)
    else:
        row.value_json = value
    return row
