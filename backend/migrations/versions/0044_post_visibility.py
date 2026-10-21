"""YouTube visibility (public/unlisted/private) on synced posts; nullable for other platforms."""

import sqlalchemy as sa
from alembic import op

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("posts") as batch:
        batch.add_column(sa.Column("visibility", sa.String(20), nullable=True))


def downgrade():
    with op.batch_alter_table("posts") as batch:
        batch.drop_column("visibility")
