"""Persist the one-time 90-day backfill without changing inbox messages."""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "comment_backfills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column(
            "account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False, unique=True
        ),
        sa.Column("window_start", sa.String(32), nullable=False),
        sa.Column("window_end", sa.String(32), nullable=False),
        sa.Column("discovery_completed_at", sa.String(32)),
    )
    # SQLite ADD COLUMN avoids rebuilding the existing cursor table.
    op.execute(
        "ALTER TABLE comment_polls ADD COLUMN backfill_id INTEGER REFERENCES comment_backfills(id)"
    )
    op.add_column("comment_polls", sa.Column("backfill_completed_at", sa.String(32)))
    op.create_index("ix_comment_polls_backfill_id", "comment_polls", ["backfill_id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM comment_backfills")).scalar():
        raise RuntimeError("已有歷史補抓進度，請使用升級前備份隔離還原")
    op.drop_index("ix_comment_polls_backfill_id", table_name="comment_polls")
    with op.batch_alter_table("comment_polls") as batch:
        batch.drop_column("backfill_completed_at")
        batch.drop_column("backfill_id")
    op.drop_table("comment_backfills")
