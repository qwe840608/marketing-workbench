"""一致 SQLite 快照、7z 加密與隔離還原；不打包 .env 或服務日誌。"""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
from contextlib import closing, contextmanager
from pathlib import Path, PureWindowsPath
from uuid import uuid4

from app.config import REPO_ROOT
from app.models.base import utc_now
from app.services.export_data import atomic_write, destination, root_path
from app.services.processes import hidden_process_kwargs

FORMAT = "mwb-backup-v1"
NAME = re.compile(r"mwb_\d{8}T\d{12}Z_[a-f0-9]{8}\.7z\Z")
KEEP = 14


class BackupError(Exception):
    pass


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def read_db(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=10)


def table_counts(connection):
    names = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return {
        name: connection.execute(
            'SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"'
        ).fetchone()[0]
        for (name,) in names
    }


def database_snapshot(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    def progress(*_):
        if time.monotonic() - started > 120:
            raise BackupError("資料庫備份逾時；未產生可用備份")

    with closing(read_db(source)) as original, closing(sqlite3.connect(target)) as snapshot:
        original.execute("BEGIN")
        counts = table_counts(original)
        original.backup(snapshot, pages=256, progress=progress, sleep=0.1)
        original.rollback()
        snapshot.execute("PRAGMA journal_mode=DELETE")
        if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise BackupError("資料庫快照完整性檢查未通過")
        if table_counts(snapshot) != counts:
            raise BackupError("資料庫快照筆數不一致")
    return counts


def archive_path(value):
    name = value.replace("\\", "/")
    path = PureWindowsPath(name)
    if path.is_absolute() or path.drive or ":" in name or ".." in path.parts or "\x00" in name:
        raise BackupError("備份含不安全路徑，拒絕還原")
    if any(
        part.endswith((".", " ")) or re.search(r'[<>:"|?*\x00-\x1f]', part) for part in path.parts
    ):
        raise BackupError("備份含不安全路徑，拒絕還原")
    if name in {"manifest.json", "database", "database/mwb.db", "export", "obsidian"}:
        return name
    if name.startswith(("export/", "obsidian/")) and all(
        part and part not in {".", ".."} for part in name.split("/")
    ):
        return name
    raise BackupError("備份含非預期項目，拒絕還原")


def run_7zip(settings, arguments, *, cwd=None):
    password = settings.backup_password.get_secret_value() if settings.backup_password else ""
    if not password or any(c in password for c in "\r\n\x00"):
        raise BackupError("請在 .env 設定單行 BACKUP_PASSWORD")
    if not settings.seven_zip_path.is_file():
        raise BackupError("找不到 7-Zip，請設定 SEVEN_ZIP_PATH")
    try:
        result = subprocess.run(
            [str(settings.seven_zip_path), *arguments, "-sccUTF-8"],
            input=(password + "\n").encode("utf-8"),
            capture_output=True,
            cwd=cwd,
            timeout=600,
            **hidden_process_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        raise BackupError("7-Zip 無法完成；請確認安裝、磁碟與權限") from None
    if result.returncode != 0:
        raise BackupError("7-Zip 驗證失敗；請確認密碼、備份檔案與磁碟空間")
    # 第三方輸出可能含客戶檔名，只在記憶體內用於驗證，不寫入日誌。
    return result.stdout.decode("utf-8", errors="replace")


def safe_listing(text):
    if "----------" not in text:
        raise BackupError("無法驗證備份內容清單")
    entries, total = set(), 0
    for block in text.split("----------", 1)[1].strip().split("\n\n"):
        fields = dict(line.split(" = ", 1) for line in block.splitlines() if " = " in line)
        if "Path" not in fields:
            continue
        path = archive_path(fields["Path"])
        if path.casefold() in entries or any(k in fields for k in ("Symbolic Link", "Hard Link")):
            raise BackupError("備份含重複路徑或連結，拒絕還原")
        is_directory = fields.get("Folder") == "+" or fields.get("Attributes", "").startswith("D")
        if (
            path.startswith(("export/", "obsidian/"))
            and not is_directory
            and Path(path).suffix.lower() not in {".md", ".docx"}
        ):
            raise BackupError("備份含非預期匯出檔案，拒絕還原")
        entries.add(path.casefold())
        total += int(fields.get("Size", "0"))
    if not {"manifest.json", "database/mwb.db"}.issubset(entries):
        raise BackupError("備份缺少清單或資料庫")
    if len(entries) > 100000 or total > 20 * 1024**3:
        raise BackupError("備份超過此版本的還原容量限制")
    return entries


def verify_tree(folder):
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != FORMAT:
        raise BackupError("此檔不是支援的工作區備份格式")
    database = folder / "database/mwb.db"
    if digest(database) != manifest["database"]["sha256"]:
        raise BackupError("還原資料庫雜湊不一致")
    with closing(read_db(database)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise BackupError("還原資料庫完整性檢查未通過")
        if table_counts(connection) != manifest["database"]["tables"]:
            raise BackupError("還原資料庫筆數不一致")
    for relative, checksum in manifest["exports"].items():
        if not archive_path(relative).startswith("export/"):
            raise BackupError("還原匯出清單不合法")
        if digest(destination(folder, relative)) != checksum:
            raise BackupError("還原匯出文件雜湊不一致")
    for relative, checksum in manifest.get("obsidian", {}).items():
        if not archive_path(relative).startswith("obsidian/"):
            raise BackupError("還原 Obsidian 清單不合法")
        if digest(destination(folder, relative)) != checksum:
            raise BackupError("還原 Obsidian 文件雜湊不一致")
    return manifest


def restore(settings, archive, target):
    archive = Path(archive).resolve()
    target = Path(target)
    if not target.is_absolute() or target.exists():
        raise BackupError("還原目的地必須是尚不存在的完整路徑，不覆蓋既有資料")
    target = target.resolve()
    protected = [
        settings.database_path.parent.resolve(),
        REPO_ROOT.resolve(),
        *settings.protected_paths,
    ]
    if any(
        (target == p or target.is_relative_to(p))
        and not (p == REPO_ROOT and target.is_relative_to(REPO_ROOT / ".runtime"))
        for p in protected
    ):
        raise BackupError("不能還原到現有資料庫或程式目錄")
    listing = run_7zip(settings, ["l", "-slt", str(archive)])
    safe_listing(listing.replace("\r\n", "\n"))
    target.mkdir(parents=True)
    run_7zip(settings, ["x", "-y", str(archive), f"-o{target}"])
    return verify_tree(target)


@contextmanager
def work_folder(settings):
    parent = (settings.database_path.parent / ".mwb-backup-work").resolve()
    parent.mkdir(parents=True, exist_ok=True)
    folder = parent / ("run-" + uuid4().hex)
    folder.mkdir()
    try:
        yield folder
    finally:
        # 僅清理由此函式建立且仍位於指定暫存根目錄下的唯一資料夾。
        if folder.resolve().parent != parent or not re.fullmatch(r"run-[a-f0-9]{32}", folder.name):
            raise BackupError("暫存路徑驗證失敗；未執行清除")
        shutil.rmtree(folder)


def copy_exports(source, target):
    source = Path(source).resolve()
    target.mkdir(parents=True, exist_ok=True)
    files = {}
    # 新安裝在第一次匯出前還沒有這個資料夾；資料庫才是正本，不能因此整晚不備份。
    if not source.exists():
        return files
    if not source.is_dir():
        raise BackupError("匯出路徑不是資料夾，請檢查 EXPORT_ROOT 設定")
    for current, dirs, names in os.walk(source, followlinks=False):
        current = Path(current)
        dirs[:] = [
            d for d in dirs if not (current / d).is_symlink() and not (current / d).is_junction()
        ]
        for name in names:
            path = current / name
            if path.is_symlink() or path.suffix.lower() not in {".md", ".docx"}:
                continue
            relative = path.relative_to(source).as_posix()
            try:
                content = path.read_bytes()
            except FileNotFoundError:
                continue  # 匯出引擎改名或移除的舊檔不屬於此次快照。
            atomic_write(target, relative, content)
            files["export/" + relative] = hashlib.sha256(content).hexdigest()
    return files


def backup_destination(value, settings, export_root):
    if value is None or not value.is_absolute() or value == Path(value.anchor):
        raise BackupError("請在 .env 設定獨立的備份資料夾完整路徑")
    target = (value / "marketing-workbench").resolve()
    protected = [
        REPO_ROOT,
        settings.database_path.parent,
        Path(export_root),
        *settings.protected_paths,
    ]
    if any(
        (target == p.resolve() or target.is_relative_to(p.resolve()))
        and not (p == REPO_ROOT and target.is_relative_to(REPO_ROOT / ".runtime"))
        for p in protected
    ):
        raise BackupError("備份不可放入程式、資料庫、匯出或知識庫目錄")
    return target


def publish(source, root, checksum, created):
    root.mkdir(parents=True, exist_ok=True)
    name = source.name
    if not NAME.fullmatch(name):
        raise BackupError("備份檔名不合法")
    target = destination(root, name)
    temp = destination(root, ".mwb-copy-" + uuid4().hex + ".partial")
    try:
        with source.open("rb") as incoming, temp.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        if digest(temp) != checksum:
            raise BackupError("備份複製雜湊不一致，未發佈檔案")
        os.replace(temp, target)
        atomic_write(
            root,
            name + ".json",
            json.dumps({"format": FORMAT, "sha256": checksum, "created_at": created}).encode(),
        )
    finally:
        if temp.exists():
            temp.unlink()
    return target


def owned_archives(root):
    result = []
    if not root.is_dir():
        return result
    for path in root.iterdir():
        if not NAME.fullmatch(path.name) or not path.is_file() or path.is_symlink():
            continue
        receipt = destination(root, path.name + ".json")
        try:
            value = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if value.get("format") == FORMAT and value.get("sha256") == digest(path):
            result.append((path, value))
    return sorted(result, key=lambda row: row[0].name, reverse=True)


def prune(root):
    for path, _ in owned_archives(root)[KEEP:]:
        # 僅刪已核對歸屬與雜湊的單一備份；不使用遞迴刪除或萬用檔名。
        destination(root, path.name).unlink()
        destination(root, path.name + ".json").unlink()


def run(settings):
    from app.db import build_engine, session_factory

    engine = build_engine(settings)
    try:
        with session_factory(engine)() as session:
            exports = root_path(session, settings)
            from app.services.obsidian import root_path as obsidian_path

            notes = obsidian_path(session, settings)
    finally:
        engine.dispose()
    local = backup_destination(settings.backup_local_root, settings, exports)
    drive = backup_destination(settings.backup_drive_root, settings, exports)
    for target in (local, drive):
        if target == notes or target.is_relative_to(notes) or notes.is_relative_to(target):
            raise BackupError("備份不可與 Obsidian 留言資料夾重疊")
    if local == drive or local.is_relative_to(drive) or drive.is_relative_to(local):
        raise BackupError("本機與 Google Drive 備份必須是不同資料夾")
    created = utc_now()
    name = f"mwb_{created.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid4().hex[:8]}.7z"
    with work_folder(settings) as work:
        payload = work / "payload"
        counts = database_snapshot(settings.database_path, payload / "database/mwb.db")
        files = copy_exports(exports, payload / "export")
        (payload / "obsidian").mkdir()
        note_files = {p.replace("export/", "obsidian/", 1): checksum
                      for p, checksum in (
                          copy_exports(notes, payload / "obsidian") if notes.is_dir() else {}
                      ).items()}
        manifest = {
            "format": FORMAT,
            "created_at": created.isoformat(),
            "database": {"tables": counts, "sha256": digest(payload / "database/mwb.db")},
            "exports": files,
            "obsidian": note_files,
        }
        (payload / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        archive = work / name
        run_7zip(
            settings,
            [
                "a",
                "-t7z",
                "-mhe=on",
                "-m0=LZMA2",
                "-mx=5",
                "-p",
                str(archive),
                "database",
                "export",
                "obsidian",
                "manifest.json",
            ],
            cwd=payload,
        )
        run_7zip(settings, ["t", str(archive)])
        # 還原到此輪唯一暫存區；所有表筆數及文件雜湊都核對後才發佈。
        restored = work / "verified"
        safe_listing(run_7zip(settings, ["l", "-slt", str(archive)]).replace("\r\n", "\n"))
        restored.mkdir()
        run_7zip(settings, ["x", "-y", str(archive), f"-o{restored}"])
        verify_tree(restored)
        checksum = digest(archive)
        published = publish(archive, local, checksum, created.isoformat())
        try:
            existing = {p.name: v["sha256"] for p, v in owned_archives(drive)}
            for path, receipt in owned_archives(local)[:KEEP]:
                if existing.get(path.name) != receipt["sha256"]:
                    publish(path, drive, receipt["sha256"], receipt["created_at"])
        except (OSError, BackupError):
            raise BackupError(
                "本機加密備份已保存；Google Drive 複製失敗，"
                "請確認已登入且磁碟可用，之後重跑會補複製"
            ) from None
        prune(local)
        prune(drive)
        return {
            "ok": True,
            "archive": name,
            "bytes": published.stat().st_size,
            "created_at": created.isoformat(),
            "tables": counts,
            "export_files": len(files),
            "restored_verified": True,
            "drive_copy_verified": True,
        }
