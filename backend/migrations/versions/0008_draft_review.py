"""草稿檢查、來源版本與報價依據。"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "drafts", sa.Column("needs_edit", sa.Boolean(), nullable=False, server_default="1")
    )
    op.add_column(
        "drafts", sa.Column("review_json", sa.JSON(), nullable=False, server_default="{}")
    )
    op.add_column("drafts", sa.Column("source_hash", sa.String(64)))
    op.add_column(
        "drafts", sa.Column("price_snapshot_json", sa.JSON(), nullable=False, server_default="[]")
    )


def downgrade():
    for name in ("price_snapshot_json", "source_hash", "review_json", "needs_edit"):
        op.drop_column("drafts", name)
