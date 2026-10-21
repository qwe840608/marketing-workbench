"""Allow a DM backfill without a lower date bound; retain existing 90-day jobs."""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("dm_backfills") as batch:
        batch.alter_column("window_start", existing_type=sa.String(32), nullable=True)
        batch.add_column(
            sa.Column("imported_messages", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM dm_backfills WHERE window_start IS NULL"))
        .scalar()
    ):
        raise RuntimeError("不可移除仍有全部歷史工作使用的日期下限")
    with op.batch_alter_table("dm_backfills") as batch:
        batch.alter_column("window_start", existing_type=sa.String(32), nullable=False)
        batch.drop_column("imported_messages")
