"""Publish targets remember when a platform post was found deleted and last checked."""

import sqlalchemy as sa
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("publish_targets") as batch:
        batch.add_column(sa.Column("deleted_at", sa.String(32)))
        batch.add_column(sa.Column("presence_checked_at", sa.String(32)))


def downgrade():
    with op.batch_alter_table("publish_targets") as batch:
        batch.drop_column("presence_checked_at")
        batch.drop_column("deleted_at")
