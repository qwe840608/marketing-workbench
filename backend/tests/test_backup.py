import json
import secrets
import sqlite3
import subprocess
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.models.base import utc_now
from app.services import backup


@pytest.fixture
def backup_settings(migrated, tmp_path):
    source = tmp_path / "source/mwb.db"
    source.parent.mkdir()
    with (
        closing(sqlite3.connect(migrated.database_path)) as original,
        closing(sqlite3.connect(source)) as target,
    ):
        original.backup(target)
    config = migrated.model_copy(
        update={
            "database_path": source,
            "backup_local_root": tmp_path / "local",
            "backup_drive_root": tmp_path / "drive",
            "backup_password": SecretStr(secrets.token_urlsafe(24) + "中文"),
        }
    )
    config.export_root.mkdir()
    (config.export_root / "sample.md").write_text("# 隔離備份驗收\n對話文字。", encoding="utf-8")
    (config.export_root / ".env").write_text("此檔不得打包", encoding="utf-8")
    (config.export_root / "runtime.log").write_text("日誌不打包", encoding="utf-8")
    config.obsidian_root.mkdir()
    (config.obsidian_root / "留言.md").write_text("# 隔離留言備份", encoding="utf-8")
    if not config.seven_zip_path.is_file():
        pytest.skip("需安裝官方 7-Zip 才可執行真實加密驗收")
    return config


def test_online_snapshot_keeps_wal_commits_and_excludes_uncommitted(tmp_path):
    path = tmp_path / "source.db"
    with closing(sqlite3.connect(path)) as live:
        live.execute("PRAGMA journal_mode=WAL")
        live.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, content TEXT)")
        live.execute("INSERT INTO messages(content) VALUES ('committed')")
        live.commit()
        live.execute("INSERT INTO messages(content) VALUES ('not committed')")
        target = tmp_path / "backup/mwb.db"
        assert backup.database_snapshot(path, target) == {"messages": 1}
        with closing(backup.read_db(target)) as restored:
            assert restored.execute("SELECT content FROM messages").fetchall() == [("committed",)]
        assert live.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2


def test_real_7zip_backup_encryption_restore_and_secret_stdin(
    backup_settings, tmp_path, monkeypatch
):
    config = backup_settings
    calls = []
    original = subprocess.run

    def checked(arguments, **kwargs):
        password = config.backup_password.get_secret_value()
        assert password not in " ".join(map(str, arguments))
        assert kwargs["input"] == (password + "\n").encode()
        calls.append(arguments)
        return original(arguments, **kwargs)

    monkeypatch.setattr(backup.subprocess, "run", checked)
    result = backup.run(config)
    assert result["ok"] and result["restored_verified"] and result["drive_copy_verified"]
    assert result["export_files"] == 1 and result["tables"]["alembic_version"] == 1
    archive = config.backup_local_root / "marketing-workbench" / result["archive"]
    cloud = config.backup_drive_root / "marketing-workbench" / result["archive"]
    assert backup.digest(archive) == backup.digest(cloud)
    destination = tmp_path / "restored"
    manifest = backup.restore(config, archive, destination)
    assert manifest["database"]["tables"] == result["tables"]
    assert (destination / "export/sample.md").read_text(encoding="utf-8").startswith("# 隔離")
    assert (destination / "obsidian/留言.md").read_text(encoding="utf-8") == "# 隔離留言備份"
    assert "obsidian/留言.md" in manifest["obsidian"]
    assert not list(destination.rglob(".env")) and not list(destination.rglob("*.log"))
    assert not list((config.database_path.parent / ".mwb-backup-work").iterdir())
    assert any("-mhe=on" in args for args in calls)
    assert "7zAES" in backup.run_7zip(config, ["l", "-slt", str(archive)])
    denied = original(
        [str(config.seven_zip_path), "l", str(archive)],
        input=b"\n",
        capture_output=True,
        timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    assert denied.returncode != 0 and b"sample.md" not in denied.stdout + denied.stderr
    wrong = config.model_copy(update={"backup_password": SecretStr(secrets.token_urlsafe(24))})
    monkeypatch.setattr(backup.subprocess, "run", original)
    with pytest.raises(backup.BackupError):
        backup.restore(wrong, archive, tmp_path / "wrong-password")
    assert not (tmp_path / "wrong-password").exists()
    with pytest.raises(backup.BackupError):
        backup.restore(config, archive, destination)


def test_copy_failure_keeps_local_and_recovers_next_run(backup_settings, monkeypatch):
    config = backup_settings
    original = backup.publish
    failed = []

    def copy(source, root, checksum, created):
        if root.is_relative_to(config.backup_drive_root):
            failed.append(True)
            raise OSError(config.backup_password.get_secret_value())
        return original(source, root, checksum, created)

    monkeypatch.setattr(backup, "publish", copy)
    with pytest.raises(backup.BackupError) as error:
        backup.run(config)
    assert "本機加密備份已保存" in str(error.value) and failed
    assert config.backup_password.get_secret_value() not in str(error.value)
    saved = list((config.backup_local_root / "marketing-workbench").glob("*.7z"))
    assert len(saved) == 1
    monkeypatch.setattr(backup, "publish", original)
    backup.run(config)
    assert (config.backup_drive_root / "marketing-workbench" / saved[0].name).is_file()


def test_retention_removes_only_owned_verified_archives(tmp_path):
    root = tmp_path / "backups"
    root.mkdir()
    files = []
    for index in range(16):
        created = utc_now() - timedelta(days=index)
        path = root / f"mwb_{created.strftime('%Y%m%dT%H%M%S%fZ')}_{index:08x}.7z"
        path.write_bytes(f"isolated retention fixture {index}".encode())
        receipt = {
            "format": backup.FORMAT,
            "sha256": backup.digest(path),
            "created_at": created.isoformat(),
        }
        path.with_suffix(".7z.json").write_text(json.dumps(receipt))
        files.append(path)
    unrelated = root / "family.7z"
    unrelated.write_bytes(b"must stay")
    unowned = root / "mwb_20200101T000000000000Z_abcdef12.7z"
    unowned.write_bytes(b"not produced by the engine")
    backup.prune(root)
    assert all(p.exists() for p in files[:14])
    assert not any(p.exists() for p in files[14:])
    assert unrelated.exists() and unowned.exists()


@pytest.mark.parametrize(
    "path",
    [
        "../outside",
        "C:/outside",
        "/outside",
        "export/../../outside",
        "export/a:stream",
        "other/file",
    ],
)
def test_restore_rejects_untrusted_archive_paths(path):
    with pytest.raises(backup.BackupError):
        backup.archive_path(path)


def test_restore_rejects_duplicate_and_link_entries():
    for suffix in [
        "Path = export/a.md\nSymbolic Link = ../../x",
        "Path = manifest.json",
        "Path = export/.env\nFolder = -",
        "Path = export/program.exe\nFolder = -",
    ]:
        text = (
            "----------\nPath = manifest.json\nSize = 10\n\n"
            "Path = database/mwb.db\nSize = 10\n\n" + suffix
        )
        with pytest.raises(backup.BackupError):
            backup.safe_listing(text)


def test_destination_cannot_overlap_source(backup_settings):
    for path in [
        backup_settings.database_path.parent,
        backup_settings.export_root,
        Path("<PROTECTED_ROOT>/knowledge"),
    ]:
        with pytest.raises(backup.BackupError):
            backup.backup_destination(path, backup_settings, backup_settings.export_root)


def test_missing_export_folder_counts_as_empty(tmp_path):
    # 新安裝還沒匯出過時資料夾不存在；夜間備份仍要保存資料庫，而不是整個失敗。
    target = tmp_path / "payload/export"
    assert backup.copy_exports(tmp_path / "never-exported", target) == {}
    assert target.is_dir() and not list(target.iterdir())
    not_folder = tmp_path / "export-file"
    not_folder.write_text("不是資料夾", encoding="utf-8")
    with pytest.raises(backup.BackupError):
        backup.copy_exports(not_folder, tmp_path / "other")


def test_backup_runs_before_first_export(backup_settings):
    config = backup_settings
    for path in config.export_root.iterdir():
        path.unlink()
    config.export_root.rmdir()
    result = backup.run(config)
    assert result["ok"] and result["export_files"] == 0
    assert result["tables"]["alembic_version"] == 1
