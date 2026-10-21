"""Administrator self-service recovery code (one-time, stored only as a hash)."""

import sqlalchemy as sa
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade():
    # 新增可為空的欄位，既有帳號維持「未設定復原碼」，不改動任何資料列。
    with op.batch_alter_table("staff") as batch:
        batch.add_column(sa.Column("recovery_code_hash", sa.String(255), nullable=True))
        batch.add_column(sa.Column("recovery_code_created_at", sa.String(32), nullable=True))


def downgrade():
    # 降版只會讓已產生的復原碼失效，不影響登入密碼。
    with op.batch_alter_table("staff") as batch:
        batch.drop_column("recovery_code_created_at")
        batch.drop_column("recovery_code_hash")
