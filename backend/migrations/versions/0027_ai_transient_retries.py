"""Persist automatic draft retry rounds; leave completed and unknown jobs untouched."""

import json

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("auto_draft_jobs") as batch:
        batch.add_column(sa.Column("attempts", sa.Integer(), server_default="0", nullable=False))
        batch.add_column(sa.Column("next_attempt_at", sa.String(32), nullable=True))
        batch.add_column(sa.Column("thread_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("provider", sa.String(20), nullable=True))
        batch.create_index("ix_auto_draft_jobs_next_attempt_at", ["next_attempt_at"])


def downgrade():
    connection = op.get_bind()
    for key, raw in connection.execute(
        sa.text("SELECT key, value_json FROM settings WHERE key LIKE 'ai.brand.%'")
    ).all():
        values = json.loads(raw)
        fields = {"gemini_fallback_model", "openai_fallback_model", "anthropic_fallback_model"}
        if fields.intersection(values):
            values = {k: v for k, v in values.items() if k not in fields}
            connection.execute(
                sa.text("UPDATE settings SET value_json=:value, version=version+1 WHERE key=:key"),
                {"key": key, "value": json.dumps(values, ensure_ascii=False)},
            )
    # 降版不能讓舊 worker 立即執行尚在等待的付費工作。
    op.execute(
        "UPDATE auto_draft_jobs SET status='skipped', reason='retry_downgraded' "
        "WHERE status='pending' AND attempts > 0"
    )
    with op.batch_alter_table("auto_draft_jobs") as batch:
        batch.drop_index("ix_auto_draft_jobs_next_attempt_at")
        batch.drop_column("provider")
        batch.drop_column("thread_version")
        batch.drop_column("next_attempt_at")
        batch.drop_column("attempts")
