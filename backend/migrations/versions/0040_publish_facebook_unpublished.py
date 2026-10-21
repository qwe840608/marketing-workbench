"""Publish drafts can ask Facebook to create an unpublished post (not shown on the Page feed)."""

import sqlalchemy as sa
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade():
    # 既有貼文一律為 false（公開）；與 0036／0038 相同，直接加欄位不重建 publish_posts。
    op.add_column(
        "publish_posts",
        sa.Column("facebook_unpublished", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("publish_posts", "facebook_unpublished")
