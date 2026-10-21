"""Locally cached post thumbnails; platform CDN links expire so the list keeps its own copy."""

import sqlalchemy as sa
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "post_thumbnails",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("mime", sa.String(32)),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("digest", sa.String(64)),
        sa.Column("data", sa.LargeBinary()),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.String(32)),
        sa.Column("error", sa.String(40)),
        sa.UniqueConstraint("post_id"),
    )


def downgrade():
    # 縮圖只是平台圖片的快取，降版刪除後升版會由每小時排程重新抓取。
    op.drop_table("post_thumbnails")
