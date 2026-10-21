"""Drop retired automatic draft jobs; downgrade restores only the empty schema."""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("auto_draft_jobs")


def downgrade():
    op.create_table(
        "auto_draft_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("message_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(80)),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.String(32)),
        sa.Column("thread_version", sa.Integer()),
        sa.Column("provider", sa.String(20)),
        sa.UniqueConstraint("message_id", "message_version"),
    )
    op.create_index("ix_auto_draft_jobs_next_attempt_at", "auto_draft_jobs", ["next_attempt_at"])
