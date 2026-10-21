"""Session-local schema snapshots; never share writable databases between tests."""

import hashlib
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app import config
from app.config import REPO_ROOT, Settings

MIGRATIONS = REPO_ROOT / "backend" / "migrations"
ALEMBIC_CONFIG = REPO_ROOT / "backend" / "alembic.ini"


def migration_fingerprint(directory: Path = MIGRATIONS) -> str:
    digest = hashlib.sha256(ALEMBIC_CONFIG.read_bytes())
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".mako"}:
            digest.update(path.relative_to(directory).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def upgrade_database(settings: Settings) -> None:
    # env.py imports Settings at execution time. Supply the explicit isolated path,
    # without loading the developer's .env or changing process-wide DATABASE_PATH.
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(config, "Settings", lambda: settings)
        command.upgrade(Config(str(ALEMBIC_CONFIG)), "head")


def copy_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    # A byte copy can miss committed WAL pages or include an incomplete transaction.
    with (
        closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)) as original,
        closing(sqlite3.connect(destination)) as target,
    ):
        original.backup(target)
        target.execute("PRAGMA journal_mode=WAL")


class MigrationTemplate:
    def __init__(self, directory: Path):
        self.directory = directory
        self.fingerprint: str | None = None
        self.path: Path | None = None
        self.generation = 0

    def copy_to(self, settings: Settings) -> None:
        fingerprint = migration_fingerprint()
        if self.fingerprint != fingerprint:
            self.generation += 1
            path = self.directory / f"template-{self.generation}.db"
            upgrade_database(settings.model_copy(update={"database_path": path}))
            self.path, self.fingerprint = path, fingerprint
        assert self.path is not None
        copy_database(self.path, settings.database_path)
        # 0014 is the only seed row in an empty upgrade. Its timestamp belongs to
        # this test's setup, just as it did with a fresh upgrade for every test.
        now = datetime.now(UTC).isoformat(timespec="microseconds")
        with closing(sqlite3.connect(settings.database_path)) as db:
            db.execute(
                "UPDATE prompt_versions SET created_at=?, updated_at=? "
                "WHERE actor='system:migration:0014'",
                (now, now),
            )
            db.commit()
