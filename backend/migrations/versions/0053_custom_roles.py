"""Custom member roles with per-feature permissions."""

import sqlalchemy as sa
from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "roles",
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
        sa.UniqueConstraint("key", name=op.f("uq_roles_key")),
    )
    # 既有成員的 admin／marketing／viewer 原樣保留；只放寬欄位讓自訂角色鍵可寫入。
    with op.batch_alter_table("staff") as batch:
        batch.drop_constraint(op.f("ck_staff_staff_role"), type_="check")
        batch.alter_column("role", existing_type=sa.String(9), type_=sa.String(40),
                           existing_nullable=False)


def downgrade():
    # 降版前把自訂角色的成員改成檢視者（權限最少），避免舊版 CHECK 拒絕資料列。
    op.execute(
        "UPDATE staff SET role = 'viewer' WHERE role NOT IN ('admin', 'marketing', 'viewer')"
    )
    with op.batch_alter_table("staff") as batch:
        batch.alter_column("role", existing_type=sa.String(40), type_=sa.String(9),
                           existing_nullable=False)
        batch.create_check_constraint(
            op.f("ck_staff_staff_role"), "role IN ('admin', 'marketing', 'viewer')"
        )
    op.drop_table("roles")
