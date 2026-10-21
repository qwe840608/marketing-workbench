"""Internal MCP OAuth and per-member agent connections."""

import sqlalchemy as sa
from alembic import op

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def table(name, *columns):
    op.create_table(name, sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("created_at", sa.String(32), nullable=False),
                    sa.Column("updated_at", sa.String(32), nullable=False), *columns)


def fk(name, target, nullable=False):
    return sa.Column(name, sa.Integer(), sa.ForeignKey(target), nullable=nullable)


def text(name, size=32, nullable=False, unique=False):
    return sa.Column(name, sa.String(size), nullable=nullable, unique=unique)


def upgrade():
    table("agent_oauth_clients", text("client_id", 80, unique=True), text("name", 100),
          sa.Column("redirect_uris", sa.JSON(), nullable=False), text("last_used_at"))
    table("agent_grants", fk("staff_id", "staff.id"),
          fk("client_id", "agent_oauth_clients.id", True), text("kind", 10), text("name", 100),
          text("last_used_at"), text("revoked_at", nullable=True))
    table("agent_oauth_requests", text("handle_hash", 64, unique=True),
          fk("client_id", "agent_oauth_clients.id"), text("redirect_uri", 2048),
          text("state", 2048), text("challenge", 43), text("expires_at"))
    table("agent_codes", text("code_hash", 64, unique=True), fk("grant_id", "agent_grants.id"),
          text("redirect_uri", 2048), text("challenge", 43), text("expires_at"),
          text("used_at", nullable=True))
    table("agent_credentials", text("token_hash", 64, unique=True),
          fk("grant_id", "agent_grants.id"), text("kind", 10), text("expires_at"),
          text("used_at", nullable=True))
    for name, columns in {
        "agent_grants": ["staff_id", "client_id", "last_used_at"],
        "agent_oauth_requests": ["client_id", "expires_at"],
        "agent_codes": ["grant_id", "expires_at"],
        "agent_credentials": ["grant_id", "expires_at"],
    }.items():
        for column in columns:
            op.create_index(f"ix_{name}_{column}", name, [column])


def downgrade():
    for name in ("agent_credentials", "agent_codes", "agent_oauth_requests",
                 "agent_grants", "agent_oauth_clients"):
        op.drop_table(name)
