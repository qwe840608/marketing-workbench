"""End pre-existing automatic work without deleting drafts or restoring old CLI settings."""

import json

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE auto_draft_jobs SET status='skipped', reason='manual_only', next_attempt_at=NULL "
        "WHERE status IN ('pending', 'processing')"
    )
    # 0021 的歷史 provider 清理及備份原樣保留；重新啟用只能經管理員的新設定。


def downgrade():
    bind = op.get_bind()
    for key, raw in bind.execute(
        sa.text(
            "SELECT key, value_json FROM settings WHERE key='ai.local_cli' OR key LIKE 'ai.brand.%'"
        )
    ).all():
        value = json.loads(raw)
        if not isinstance(value, dict):
            continue
        changed = False
        if key == "ai.local_cli":
            for provider in ("codex_cli", "claude_cli", "agy_cli"):
                if isinstance(value.get(provider), dict) and value[provider].get("enabled"):
                    value[provider]["enabled"], changed = False, True
            if value.get("auto_draft_worker_enabled"):
                value["auto_draft_worker_enabled"], changed = False, True
        elif value.get("manual_provider") in {"codex_cli", "claude_cli", "agy_cli"}:
            value["manual_provider"], changed = None, True
        if changed:
            bind.execute(
                sa.text("UPDATE settings SET value_json=:value, version=version+1 WHERE key=:key"),
                {"key": key, "value": json.dumps(value, ensure_ascii=False)},
            )
    # 安全結束不可重播，降版保留 skipped；草稿與全部歷史用量原樣保留。
