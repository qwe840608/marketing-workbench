"""Session-bound OAuth and safe connection metadata."""

import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade():
    def common():
        return [
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.String(32), nullable=False),
            sa.Column("updated_at", sa.String(32), nullable=False),
        ]
    op.create_table(
        "oauth_states",
        *common(),
        sa.Column("state_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("session_hash", sa.String(64), nullable=False),
        sa.Column("staff_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.String(32), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
    )
    op.create_table(
        "oauth_connections",
        *common(),
        sa.Column("platform", sa.String(16), nullable=False, unique=True),
        sa.Column("account_name", sa.String(255), nullable=False),
        sa.Column("ig_username", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.String(32)),
        sa.Column("refreshed_at", sa.String(32)),
        sa.Column("granted_scopes", sa.JSON(), nullable=False),
        sa.Column("cache_json", sa.JSON(), nullable=False),
        sa.Column("checked_at", sa.String(32)),
        sa.Column("credential_digest", sa.String(64), nullable=False),
        sa.Column("maintenance_at", sa.String(32)),
        sa.Column("notified_at", sa.String(32)),
    )


def downgrade():
    op.drop_table("oauth_connections")
    op.drop_table("oauth_states")
