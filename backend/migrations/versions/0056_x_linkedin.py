"""X and LinkedIn: allow the new platforms and keep the PKCE verifier on the OAuth state."""

import sqlalchemy as sa
from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None

OLD = ("line", "facebook", "instagram", "youtube", "tiktok", "threads")
NEW = OLD + ("x", "linkedin")
PUBLISH_OLD = ("facebook", "instagram", "threads", "youtube", "tiktok")
PUBLISH_NEW = PUBLISH_OLD + ("x", "linkedin")
# (資料表, 約束名稱)：與 0002 的 Enum 名稱一致，命名規則會加上 ck_<資料表>_ 前綴。
DOMAIN = (
    ("accounts", "account_platform"),
    ("contacts", "contact_platform"),
    ("raw_events", "event_platform"),
)


def listing(values):
    return ",".join(f"'{value}'" for value in values)


def replace(table, name, values):
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(op.f(f"ck_{table}_{name}"), type_="check")
        batch.create_check_constraint(name, f"platform IN ({listing(values)})")


def upgrade():
    # 只放寬平台清單與新增空白欄位，不改動任何既有資料列。
    for table, name in DOMAIN:
        replace(table, name, NEW)
    replace("publish_targets", "platform", PUBLISH_NEW)
    with op.batch_alter_table("oauth_states") as batch:
        batch.add_column(
            sa.Column("encrypted_verifier", sa.Text(), nullable=False, server_default="")
        )


def downgrade():
    # 舊 schema 不容許 X／LinkedIn；有資料時禁止降版，操作人需先評估與備份。
    bind = op.get_bind()
    for table, _ in (*DOMAIN, ("publish_targets", "platform")):
        count = bind.scalar(
            sa.text(f"SELECT count(*) FROM {table} WHERE platform IN ('x','linkedin')")
        )
        if count:
            raise RuntimeError("Existing X or LinkedIn rows prevent downgrade")
    with op.batch_alter_table("oauth_states") as batch:
        batch.drop_column("encrypted_verifier")
    replace("publish_targets", "platform", PUBLISH_OLD)
    for table, name in DOMAIN:
        replace(table, name, OLD)
