"""Default-off emergency sending and durable draft/send claims."""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def base_columns():
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    ]


def upgrade():
    op.add_column(
        "accounts", sa.Column("send_enabled", sa.Boolean(), nullable=False, server_default="0")
    )
    op.add_column(
        "brands",
        sa.Column("marketing_dm_enabled", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.execute("ALTER TABLE messages ADD COLUMN sent_by_staff_id INTEGER REFERENCES staff(id)")
    op.add_column("messages", sa.Column("sender_name", sa.String(200)))
    op.create_table(
        "send_attempts",
        *base_columns(),
        sa.Column("key", sa.String(36), nullable=False, unique=True),
        sa.Column("thread_id", sa.Integer(), sa.ForeignKey("threads.id"), nullable=False),
        sa.Column("staff_id", sa.Integer(), sa.ForeignKey("staff.id"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("target", sa.String(255), nullable=False),
        sa.Column("target_name", sa.String(200), nullable=False),
        sa.Column("context_hash", sa.String(64), nullable=False),
        sa.Column("review_json", sa.JSON(), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.String(32), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
    )
    op.create_table(
        "line_reply_credentials",
        *base_columns(),
        sa.Column(
            "message_id", sa.Integer(), sa.ForeignKey("messages.id"), nullable=False, unique=True
        ),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("received_at", sa.String(32), nullable=False),
        sa.Column("used_at", sa.String(32)),
    )
    op.create_table(
        "auto_draft_jobs",
        *base_columns(),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("message_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reason", sa.String(80)),
        sa.UniqueConstraint("message_id", "message_version"),
    )


def downgrade():
    db = op.get_bind()
    if any(
        db.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar()
        for table in ("send_attempts", "line_reply_credentials", "auto_draft_jobs")
    ):
        raise RuntimeError("已有送出或草稿稽核，無法無損降回；請以升級前備份隔離還原")
    for table in ("auto_draft_jobs", "line_reply_credentials", "send_attempts"):
        op.drop_table(table)
    # Later batch rebuilds turn the inline reference into a table constraint.
    with op.batch_alter_table(
        "messages",
        recreate="always",
        naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"},
    ) as batch:
        batch.drop_constraint("fk_messages_sent_by_staff_id_staff", type_="foreignkey")
        batch.drop_column("sent_by_staff_id")
    op.execute("ALTER TABLE messages DROP COLUMN sender_name")
    op.execute("ALTER TABLE accounts DROP COLUMN send_enabled")
    op.execute("ALTER TABLE brands DROP COLUMN marketing_dm_enabled")
