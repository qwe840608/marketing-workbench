"""Platform options and durable Threads chain checkpoints."""

import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade():
    # 不重建資料表；舊影片維持 /videos，IG 預設與既有省略參數的請求相容。
    legacy = {
        "facebook": {"video_format": "feed"},
        "instagram": {"share_to_feed": True},
        "threads": {"segments": [], "segments_custom": False},
    }
    op.add_column(
        "publish_posts",
        sa.Column("platform_options_json", sa.JSON(), nullable=False, server_default="{}"),
    )
    table = sa.table("publish_posts", sa.column("platform_options_json", sa.JSON()))
    op.execute(table.update().values(platform_options_json=legacy))
    op.add_column(
        "publish_targets",
        sa.Column("detail_json", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade():
    op.drop_column("publish_targets", "detail_json")
    op.drop_column("publish_posts", "platform_options_json")
