"""Persist notification delivery, retry identity and message provenance."""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("brand_id", sa.Integer(), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("retry_key", sa.String(36), nullable=False, unique=True),
        sa.Column("recipient", sa.String(64), nullable=False),
        sa.Column("messages_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_id", sa.String(36)),
        sa.Column("lease_until", sa.String(32)),
        sa.Column("first_attempt_at", sa.String(32)),
        sa.Column("next_attempt_at", sa.String(32), nullable=False),
        sa.Column("sent_at", sa.String(32)),
        sa.Column("error", sa.String(80)),
    )
    op.create_index("ix_notification_deliveries_brand_id", "notification_deliveries", ["brand_id"])
    op.create_index("ix_notification_deliveries_status", "notification_deliveries", ["status"])
    with op.batch_alter_table("notifications") as batch:
        batch.drop_constraint("uq_notifications_thread_id", type_="unique")
        batch.add_column(sa.Column("event_key", sa.String(160)))
        batch.add_column(sa.Column("message_id", sa.Integer()))
        batch.add_column(sa.Column("reason", sa.String(40)))
        batch.add_column(sa.Column("delivery_id", sa.Integer()))
        batch.create_unique_constraint("uq_notifications_event_key", ["event_key"])
        batch.create_foreign_key("fk_notifications_message", "messages", ["message_id"], ["id"])
        batch.create_foreign_key(
            "fk_notifications_delivery", "notification_deliveries", ["delivery_id"], ["id"]
        )


def downgrade():
    with op.batch_alter_table("notifications") as batch:
        batch.create_unique_constraint(
            "uq_notifications_thread_id", ["thread_id", "kind", "due_at"]
        )
        batch.drop_constraint("fk_notifications_delivery", type_="foreignkey")
        batch.drop_constraint("fk_notifications_message", type_="foreignkey")
        batch.drop_constraint("uq_notifications_event_key", type_="unique")
        for column in ("delivery_id", "reason", "message_id", "event_key"):
            batch.drop_column(column)
    op.drop_table("notification_deliveries")
