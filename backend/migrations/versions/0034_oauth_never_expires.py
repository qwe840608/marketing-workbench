"""Record OAuth grants that Meta reports as never expiring."""

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("oauth_connections") as batch:
        batch.add_column(
            sa.Column("never_expires", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade():
    with op.batch_alter_table("oauth_connections") as batch:
        batch.drop_column("never_expires")
