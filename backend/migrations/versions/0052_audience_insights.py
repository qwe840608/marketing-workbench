"""Latest audience breakdowns per account (age, gender, location, online hours)."""

import sqlalchemy as sa
from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audience_insights",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("metric", sa.String(16), nullable=False),
        sa.Column("breakdown", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.String(40)),
        sa.Column("period", sa.String(32), nullable=False),
        sa.Column("items_json", sa.JSON(), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False),
        sa.Column("fetched_at", sa.String(32), nullable=False),
        sa.UniqueConstraint("account_id", "metric", "breakdown"),
    )


def downgrade():
    # 受眾分布只是平台數據的最新快取，降版刪除後升版會由每小時排程重新抓取。
    op.drop_table("audience_insights")
