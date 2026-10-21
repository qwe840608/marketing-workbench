"""保存分流政策、可重用判斷及工作租約。"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("inbound_jobs", sa.Column("lease_id", sa.String(36)))
    op.add_column("inbound_jobs", sa.Column("lease_until", sa.String(32)))
    op.add_column("classifications", sa.Column("input_hash", sa.String(64)))
    op.add_column("classifications", sa.Column("urgency", sa.Float()))
    op.add_column("classifications", sa.Column("sentiment_score", sa.Float()))
    op.add_column(
        "classifications", sa.Column("policy_json", sa.JSON(), nullable=False, server_default="{}")
    )
    op.add_column(
        "classifications", sa.Column("reasons_json", sa.JSON(), nullable=False, server_default="[]")
    )
    op.add_column("ai_runs", sa.Column("duration_ms", sa.Integer()))


def downgrade():
    op.drop_column("ai_runs", "duration_ms")
    for name in ("reasons_json", "policy_json", "sentiment_score", "urgency", "input_hash"):
        op.drop_column("classifications", name)
    op.drop_column("inbound_jobs", "lease_until")
    op.drop_column("inbound_jobs", "lease_id")
