"""保留無法解析的來源、每則訊息的聯絡人，以及待分類／通知的持久化工作。"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite 原生 ADD COLUMN 避免重建 messages，保留其他資料表對既有訊息的參照。
    op.execute(
        "ALTER TABLE messages ADD COLUMN contact_id INTEGER "
        "CONSTRAINT fk_messages_contact_id_contacts REFERENCES contacts (id)"
    )
    with op.batch_alter_table("raw_events") as batch:
        batch.alter_column("platform", existing_type=sa.String(9), nullable=True)
    op.create_table(
        "inbound_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column(
            "task",
            sa.Enum(
                "classify",
                "notify",
                name="inbound_task",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "processing",
                "completed",
                "failed",
                name="inbound_job_status",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inbound_jobs")),
        sa.ForeignKeyConstraint(
            ["message_id"], ["messages.id"], name=op.f("fk_inbound_jobs_message_id_messages")
        ),
        sa.UniqueConstraint("message_id", "task", name=op.f("uq_inbound_jobs_message_id")),
    )
    op.create_index(op.f("ix_inbound_jobs_message_id"), "inbound_jobs", ["message_id"])
    op.create_index(op.f("ix_inbound_jobs_status"), "inbound_jobs", ["status"])


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM raw_events WHERE platform IS NULL")):
        raise RuntimeError("有平台不明的原始事件，無法無損降回 0003；請先備份處理。")
    op.drop_table("inbound_jobs")
    with op.batch_alter_table("raw_events") as batch:
        batch.alter_column("platform", existing_type=sa.String(9), nullable=False)
    # Batch rebuilds in later revisions materialize the inline foreign key.
    with op.batch_alter_table(
        "messages",
        recreate="always",
        naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"},
    ) as batch:
        batch.drop_constraint("fk_messages_contact_id_contacts", type_="foreignkey")
        batch.drop_column("contact_id")
