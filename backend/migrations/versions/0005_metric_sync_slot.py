"""保留實際抓取時間，另外以排程時槽去重。"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("metric_snapshots", sa.Column("sync_slot", sa.String(32), nullable=True))
    op.create_index(
        "uq_metric_post_sync_slot", "metric_snapshots", ["post_id", "sync_slot"], unique=True
    )


def downgrade():
    op.drop_index("uq_metric_post_sync_slot", table_name="metric_snapshots")
    op.drop_column("metric_snapshots", "sync_slot")
