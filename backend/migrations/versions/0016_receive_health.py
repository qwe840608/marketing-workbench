"""Independent inbound monitoring; no changes to account switches or messages."""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def base_columns():
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    ]


def upgrade():
    op.create_table(
        "receive_health_checks",
        *base_columns(),
        sa.Column("checked_at", sa.String(32), nullable=False),
        sa.Column("healthy", sa.Boolean(), nullable=False),
        sa.Column("checks_json", sa.JSON(), nullable=False),
        sa.Column("transition", sa.String(20)),
        sa.Column("alert_status", sa.String(32), nullable=False),
    )
    op.create_index("ix_receive_health_checks_checked_at", "receive_health_checks", ["checked_at"])
    op.create_table(
        "webhook_failures",
        *base_columns(),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("bucket_at", sa.String(32), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("platform", "bucket_at"),
    )
    op.create_index("ix_webhook_failures_bucket_at", "webhook_failures", ["bucket_at"])


def downgrade():
    for name in ("receive_health_checks", "webhook_failures"):
        if op.get_bind().execute(sa.text(f"SELECT count(*) FROM {name}")).scalar():
            raise RuntimeError("健康監測紀錄已存在，不允許破壞性降版")
    op.drop_table("webhook_failures")
    op.drop_table("receive_health_checks")
