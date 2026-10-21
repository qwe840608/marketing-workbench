"""Member password rotation and persistent login throttling."""

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "staff",
        sa.Column(
            "must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.create_table(
        "login_guards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("account_key", sa.String(64), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.String(32)),
        sa.UniqueConstraint("account_key", name="uq_login_guards_account_key"),
    )


def downgrade():
    op.drop_table("login_guards")
    op.drop_column("staff", "must_change_password")
