"""Encrypted platform configuration and the existing jev credential."""

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "platform_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False, unique=True),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
    )
    op.execute(
        "INSERT INTO platform_credentials (created_at, updated_at, version, provider, "
        "encrypted_key) SELECT created_at, updated_at, version, 'JEV_API_KEY', "
        "encrypted_key FROM ai_credentials WHERE provider = 'jev'"
    )
    op.execute("DELETE FROM ai_credentials WHERE provider = 'jev'")
    op.execute("DELETE FROM ai_key_verifications WHERE provider = 'jev'")


def downgrade():
    db = op.get_bind()
    if db.execute(
        sa.text(
            "SELECT count(*) FROM platform_credentials "
            "WHERE provider != 'JEV_API_KEY' AND encrypted_key != ''"
        )
    ).scalar():
        raise RuntimeError("平台憑證已設定，請以升級前備份隔離還原")
    op.execute(
        "INSERT INTO ai_credentials (created_at, updated_at, version, provider, "
        "encrypted_key) SELECT created_at, updated_at, version, 'jev', encrypted_key "
        "FROM platform_credentials WHERE provider = 'JEV_API_KEY' AND encrypted_key != ''"
    )
    op.drop_table("platform_credentials")
