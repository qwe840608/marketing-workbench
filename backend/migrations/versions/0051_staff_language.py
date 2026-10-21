"""Per-account interface language preference."""

import sqlalchemy as sa
from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade():
    # 可為空：既有帳號維持原本的繁體中文介面，不改動任何資料列。
    with op.batch_alter_table("staff") as batch:
        batch.add_column(sa.Column("language", sa.String(10), nullable=True))


def downgrade():
    # 降版只會讓介面回到瀏覽器記住的語言。
    with op.batch_alter_table("staff") as batch:
        batch.drop_column("language")
