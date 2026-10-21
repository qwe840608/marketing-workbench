from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import HTTPException

from app.services import settings_store
from app.services.export_data import validate_root
from app.services.posts import _begin_ingest

EXPORT_KEY = "export_root"


def export_view(access, settings, *, key=EXPORT_KEY):
    if access.staff.role != "admin":
        raise HTTPException(403, "匯出目錄為全域設定，僅管理員可操作")
    row = settings_store.get(access.session, key)
    return {
        key: row.value_json if row else str(getattr(settings, key)),
        "version": settings_store.version(row),
        "engine_available": True,
    }


def save_export(access, body, settings, *, key=EXPORT_KEY):
    if export_view(access, settings, key=key)["version"] != body.version:
        raise HTTPException(409, "匯出設定已更新，請重新整理")
    path = Path(getattr(body, key).strip())
    if not path.is_absolute() or "\x00" in str(path):
        raise HTTPException(422, "請填寫本機的完整資料夾路徑")
    try:
        path = validate_root(path, settings, obsidian=key == "obsidian_root")
        path.mkdir(parents=True, exist_ok=True)
        # 使用唯一暫存檔驗證實際寫入，避免覆蓋使用者的檔案。
        with NamedTemporaryFile(prefix=".mwb-write-check-", dir=path) as probe:
            probe.write(b"mwb")
            probe.flush()
    except (OSError, ValueError):
        raise HTTPException(422, "此目錄無法寫入，請確認路徑及資料夾權限") from None
    session, actor = access.session, f"staff:{access.staff.id}"
    session.commit()
    with session.begin():
        audit = _begin_ingest(
            session, "obsidian.settings" if key == "obsidian_root" else "export.settings"
        )
        row = settings_store.get(session, key)
        settings_store.require_version(row, body.version, "匯出設定已更新，請重新整理")
        before = row.value_json if row else str(getattr(settings, key))
        value = str(path)
        settings_store.put(session, key, value, row)
        audit.actor = actor
        audit.detail_json = {"before": before, "after": value}
    return {**export_view(access, settings, key=key), "writable": True}
