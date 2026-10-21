"""Separate one-off manual reads from automatic comment polling."""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("comment_polls", sa.Column("last_auto_completed_at", sa.String(32)))
    op.add_column(
        "comment_polls",
        sa.Column("manual_requested", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade():
    with op.batch_alter_table("comment_polls") as batch:
        batch.drop_column("manual_requested")
        batch.drop_column("last_auto_completed_at")
