"""Durable read-only DM backfill and LINE delivery provenance."""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("is_historical", "is_redelivery"):
        op.add_column(
            "messages", sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false())
        )
    op.create_table(
        "dm_backfills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column(
            "account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False, unique=True
        ),
        sa.Column("window_start", sa.String(32), nullable=False),
        sa.Column("window_end", sa.String(32), nullable=False),
        sa.Column("completed_at", sa.String(32)),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("next_poll_at", sa.String(32), nullable=False),
        sa.Column("run_id", sa.String(36), unique=True),
        sa.Column("lease_until", sa.String(32)),
        sa.Column("progress_json", sa.JSON(), nullable=False),
        sa.Column("last_error", sa.String(40)),
        sa.Column("permissions_json", sa.JSON(), nullable=False),
    )


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT (SELECT count(*) FROM dm_backfills) + "
                "(SELECT count(*) FROM messages WHERE is_historical = 1 OR is_redelivery = 1)"
            )
        )
        .scalar()
    ):
        raise RuntimeError("不可刪除歷史補抓與補送稽核資料")
    op.drop_table("dm_backfills")
    op.drop_column("messages", "is_redelivery")
    op.drop_column("messages", "is_historical")
