"""Store locally observed follower counts without backfilling platform history."""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "follower_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("captured_at", sa.String(32), nullable=False),
        sa.Column("followers_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("account_id", "captured_at"),
        sa.CheckConstraint("followers_count >= 0", name="nonnegative_count"),
    )


def downgrade():
    op.drop_table("follower_snapshots")
