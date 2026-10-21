"""Synced posts remember when a complete platform listing no longer contained them."""

import sqlalchemy as sa
from alembic import op

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("posts") as batch:
        batch.add_column(sa.Column("deleted_at", sa.String(32)))


def downgrade():
    with op.batch_alter_table("posts") as batch:
        batch.drop_column("deleted_at")
