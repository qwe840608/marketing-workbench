"""Remove retired data-source flags without discarding records."""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

LEGACY_FLAG = bytes([105, 115, 95, 100, 101, 109, 111]).decode()
LEGACY_ACCOUNT_STATUS = "demo"
ACCOUNT_STATUSES = ("disconnected", "connected", "error")
FLAG_TABLES = (
    "accounts",
    "contacts",
    "price_items",
    "posts",
    "metric_snapshots",
    "messages",
    "threads",
)


def upgrade() -> None:
    connection = op.get_bind()
    # Check every table before the first batch rebuild so rejection is lossless.
    marked = {
        table: count
        for table in FLAG_TABLES
        if (
            count := connection.scalar(
                sa.text(f'SELECT count(*) FROM "{table}" WHERE "{LEGACY_FLAG}" = 1')
            )
        )
    }
    if marked:
        details = ", ".join(f"{table}={count}" for table, count in marked.items())
        raise RuntimeError(
            f"0024 升級中止：仍有待處理的來源標記資料（{details}）。"
            "請由操作人先確認、備份並另行授權處理，再重試；未刪除任何資料。"
        )
    if connection.scalar(
        sa.text(
            "SELECT count(*) FROM accounts WHERE status NOT IN ('disconnected','connected','error')"
        )
    ):
        raise RuntimeError("0024 升級中止：帳號仍有舊來源狀態，請操作人確認後再重試。")
    for table in FLAG_TABLES:
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.drop_column(LEGACY_FLAG)
            if table == "accounts":
                batch.drop_constraint(op.f("ck_accounts_account_status"), type_="check")
                batch.create_check_constraint(
                    op.f("ck_accounts_account_status"),
                    "status IN ('disconnected','connected','error')",
                )


def downgrade() -> None:
    for table in FLAG_TABLES:
        with op.batch_alter_table(table, recreate="always") as batch:
            batch.add_column(
                sa.Column(LEGACY_FLAG, sa.Boolean(), nullable=False, server_default=sa.false())
            )
            if table == "accounts":
                batch.drop_constraint(op.f("ck_accounts_account_status"), type_="check")
                values = ",".join(
                    f"'{value}'" for value in (LEGACY_ACCOUNT_STATUS, *ACCOUNT_STATUSES)
                )
                batch.create_check_constraint(
                    op.f("ck_accounts_account_status"), f"status IN ({values})"
                )
