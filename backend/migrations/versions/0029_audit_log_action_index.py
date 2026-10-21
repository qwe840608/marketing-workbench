"""Index audit rows by action and time for retention and lookups."""

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_audit_log_action_at", "audit_log", ["action", "at"])


def downgrade():
    op.drop_index("ix_audit_log_action_at", table_name="audit_log")
