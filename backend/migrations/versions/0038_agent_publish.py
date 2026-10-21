"""Agent publication sources, upload capabilities and two step confirmations."""

import sqlalchemy as sa
from alembic import op

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "publish_posts", sa.Column("source_json", sa.JSON(), nullable=False, server_default="{}")
    )
    op.add_column(
        "publish_posts",
        sa.Column("agent_publish_json", sa.JSON(), nullable=False, server_default="{}"),
    )
    for name in ("agent_uploads", "agent_publish_confirmations"):
        fields = [
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.String(32), nullable=False),
            sa.Column("updated_at", sa.String(32), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("post_id", sa.Integer(), sa.ForeignKey("publish_posts.id"), nullable=False),
            sa.Column("grant_id", sa.Integer(), sa.ForeignKey("agent_grants.id"), nullable=False),
            sa.Column("staff_id", sa.Integer(), sa.ForeignKey("staff.id"), nullable=False),
            sa.Column("expires_at", sa.String(32), nullable=False),
            sa.Column("used_at", sa.String(32)),
        ]
        if name == "agent_uploads":
            fields.append(sa.Column("filename", sa.String(255), nullable=False))
        else:
            fields += [
                sa.Column("post_version", sa.Integer(), nullable=False),
                sa.Column("detail_hash", sa.String(64), nullable=False),
                sa.Column("scheduled_at", sa.String(32)),
                sa.Column("retry", sa.Boolean(), nullable=False),
            ]
        op.create_table(name, *fields)
        op.create_index("ix_" + name + "_expires_at", name, ["expires_at"])


def downgrade():
    op.drop_table("agent_publish_confirmations")
    op.drop_table("agent_uploads")
    op.drop_column("publish_posts", "agent_publish_json")
    op.drop_column("publish_posts", "source_json")
