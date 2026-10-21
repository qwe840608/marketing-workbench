"""持久化 IG 留言補抓進度、來源與 Meta 用量紀錄。"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def base_columns():
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    ]


def upgrade():
    op.add_column(
        "raw_events", sa.Column("source", sa.String(16), nullable=False, server_default="webhook")
    )
    op.add_column(
        "messages",
        sa.Column("sources_json", sa.JSON(), nullable=False, server_default='["webhook"]'),
    )
    op.add_column("messages", sa.Column("content_observed_at", sa.String(32)))
    op.create_table(
        "comment_polls",
        *base_columns(),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("post_id", sa.Integer(), sa.ForeignKey("posts.id"), unique=True),
        sa.Column("resource", sa.String(255), nullable=False),
        sa.Column("last_completed_at", sa.String(32)),
        sa.Column("next_poll_at", sa.String(32), nullable=False),
        sa.Column("requested_at", sa.String(32)),
        sa.Column("run_id", sa.String(36), unique=True),
        sa.Column("lease_until", sa.String(32)),
        sa.Column("progress_json", sa.JSON(), nullable=False),
        sa.Column("last_error", sa.String(40)),
        sa.UniqueConstraint("account_id", "resource"),
    )
    op.create_index("ix_comment_polls_next_poll_at", "comment_polls", ["next_poll_at"])
    op.create_table(
        "meta_api_calls",
        *base_columns(),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("operation", sa.String(24), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=False),
        sa.Column("run_id", sa.String(36)),
        sa.Column("completed_at", sa.String(32)),
        sa.Column("http_status", sa.Integer()),
        sa.Column("error_code", sa.Integer()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("usage_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_meta_api_calls_created_at", "meta_api_calls", ["created_at"])


def downgrade():
    op.drop_table("meta_api_calls")
    op.drop_table("comment_polls")
    op.drop_column("messages", "content_observed_at")
    op.drop_column("messages", "sources_json")
    op.drop_column("raw_events", "source")
