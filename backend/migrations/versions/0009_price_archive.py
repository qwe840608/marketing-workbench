"""價目封存保留報價依據與歷史。"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "price_items", sa.Column("archived", sa.Boolean(), nullable=False, server_default="0")
    )


def downgrade():
    op.drop_column("price_items", "archived")
