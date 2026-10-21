"""Publishing records, durable targets and hashed temporary media capabilities."""

import sqlalchemy as sa
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def base():
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    ]


def upgrade():
    op.create_table(
        "publish_posts",
        *base(),
        sa.Column("brand_id", sa.Integer(), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("creator_id", sa.Integer(), sa.ForeignKey("staff.id"), nullable=False),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("captions_json", sa.JSON(), nullable=False),
        sa.Column("platforms_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("scheduled_at", sa.String(32)),
        sa.Column("locked_at", sa.String(32)),
        sa.Column("completed_at", sa.String(32)),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("report_id", sa.Integer()),
        sa.Column("idea_index", sa.Integer()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint("format IN ('video','image','carousel','text')", name="format"),
        sa.CheckConstraint(
            "status IN ('draft','scheduled','publishing','done','partial','failed',"
            "'missed','paused','cancelled')",
            name="status",
        ),
    )
    for column in ("brand_id", "status", "scheduled_at", "report_id"):
        op.create_index("ix_publish_posts_" + column, "publish_posts", [column])
    op.create_table(
        "publish_media",
        *base(),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("publish_posts.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("relative_path", sa.String(80), nullable=False, unique=True),
        sa.Column("mime", sa.String(32), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("duration", sa.Float()),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("uploader_id", sa.Integer(), sa.ForeignKey("staff.id"), nullable=False),
        sa.Column("deleted_at", sa.String(32)),
    )
    op.create_index("ix_publish_media_post_id", "publish_media", ["post_id"])
    op.create_table(
        "publish_targets",
        *base(),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("publish_posts.id"), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("platform_post_id", sa.String(128)),
        sa.Column("permalink", sa.Text()),
        sa.Column("error_code", sa.String(32)),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.String(32)),
        sa.UniqueConstraint("post_id", "platform"),
        sa.CheckConstraint("platform IN ('facebook','instagram','threads')", name="platform"),
        sa.CheckConstraint(
            "status IN ('pending','publishing','succeeded','failed')", name="status"
        ),
    )
    op.create_index("ix_publish_targets_post_id", "publish_targets", ["post_id"])
    op.create_table(
        "publish_links",
        *base(),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("media_id", sa.Integer(), sa.ForeignKey("publish_media.id"), nullable=False),
        sa.Column("expires_at", sa.String(32), nullable=False),
        sa.Column("uses", sa.Integer(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("revoked_at", sa.String(32)),
    )
    op.create_index("ix_publish_links_media_id", "publish_links", ["media_id"])


def downgrade():
    for table in ("publish_links", "publish_targets", "publish_media", "publish_posts"):
        op.drop_table(table)
