"""Clear retired provider selections without changing historical records."""

import copy
import json

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

# Only this migration retains old identifiers; regression tests import this constant.
RETIRED_PROVIDERS = ("codex_cli", "claude_cli", "agy_cli")
BACKUP_TABLE = "retired_provider_settings"


def cleared(value, path=(), *, setting_key=""):
    """Inspect provider fields, including nested workspace/brand/default settings."""
    if not path and "provider" in setting_key and isinstance(value, str):
        if value in RETIRED_PROVIDERS:
            return None, [{"path": [], "old": value}]
    changes = []
    result = copy.deepcopy(value)
    if isinstance(result, dict):
        for key, item in result.items():
            location = (*path, key)
            if "provider" in key and isinstance(item, str) and item in RETIRED_PROVIDERS:
                changes.append({"path": list(location), "old": item})
                result[key] = None
            else:
                result[key], nested = cleared(item, location)
                changes.extend(nested)
    elif isinstance(result, list):
        for index, item in enumerate(result):
            result[index], nested = cleared(item, (*path, index))
            changes.extend(nested)
    return result, changes


def decoded(value):
    # SQLite JSON affinity may return scalar numbers directly from older settings.
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def settings_table():
    return sa.table(
        "settings",
        sa.column("key", sa.String),
        sa.column("value_json", sa.JSON),
        sa.column("version", sa.Integer),
    )


def backup_table():
    return sa.table(
        BACKUP_TABLE,
        sa.column("key", sa.String),
        sa.column("changes_json", sa.JSON),
        sa.column("original_version", sa.Integer),
    )


def upgrade():
    op.create_table(
        BACKUP_TABLE,
        sa.Column("key", sa.String(120), primary_key=True),
        sa.Column("changes_json", sa.JSON(), nullable=False),
        sa.Column("original_version", sa.Integer(), nullable=False),
    )
    bind, settings, backup = op.get_bind(), settings_table(), backup_table()
    for row in bind.execute(sa.text("SELECT key, value_json, version FROM settings")).mappings():
        value, changes = cleared(decoded(row["value_json"]), setting_key=row["key"])
        if not changes:
            continue
        # Save only provider paths and identifiers, never credentials or other settings.
        bind.execute(
            backup.insert().values(
                key=row["key"], changes_json=changes, original_version=row["version"]
            )
        )
        bind.execute(
            settings.update()
            .where(settings.c.key == row["key"])
            .values(value_json=value, version=row["version"] + 1)
        )


def downgrade():
    bind, settings, backup = op.get_bind(), settings_table(), backup_table()
    for saved in bind.execute(sa.select(backup)).mappings().all():
        row = (
            bind.execute(
                sa.text("SELECT key, value_json, version FROM settings WHERE key = :key"),
                {"key": saved["key"]},
            )
            .mappings()
            .first()
        )
        if row is None:
            continue
        value, restored = decoded(row["value_json"]), False
        for change in saved["changes_json"]:
            if not change["path"]:
                if value is None:
                    value, restored = change["old"], True
                continue
            try:
                parent = value
                for part in change["path"][:-1]:
                    parent = parent[part]
                field = change["path"][-1]
                # Preserve choices made after deployment rather than overwriting them.
                if parent[field] is None:
                    parent[field], restored = change["old"], True
            except (KeyError, IndexError, TypeError):
                continue
        if restored:
            version = row["version"] + 1
            if row["version"] == saved["original_version"] + 1:
                version = saved["original_version"]
            bind.execute(
                settings.update()
                .where(settings.c.key == saved["key"])
                .values(value_json=value, version=version)
            )
    op.drop_table(BACKUP_TABLE)
