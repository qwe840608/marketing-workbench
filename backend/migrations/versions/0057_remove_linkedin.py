"""Remove LinkedIn: without a Page of the author's own, the app cannot get Share on LinkedIn."""

import sqlalchemy as sa
from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None

WITH = ("line", "facebook", "instagram", "youtube", "tiktok", "threads", "x", "linkedin")
WITHOUT = tuple(value for value in WITH if value != "linkedin")
PUBLISH_WITH = ("facebook", "instagram", "threads", "youtube", "tiktok", "x", "linkedin")
PUBLISH_WITHOUT = tuple(value for value in PUBLISH_WITH if value != "linkedin")
# (資料表, 約束名稱)：與 0002／0056 一致，命名規則會加上 ck_<資料表>_ 前綴。
TABLES = (
    ("accounts", "account_platform", WITH, WITHOUT),
    ("contacts", "contact_platform", WITH, WITHOUT),
    ("raw_events", "event_platform", WITH, WITHOUT),
    ("publish_targets", "platform", PUBLISH_WITH, PUBLISH_WITHOUT),
)


def listing(values):
    return ",".join(f"'{value}'" for value in values)


def replace(table, name, values):
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(op.f(f"ck_{table}_{name}"), type_="check")
        batch.create_check_constraint(name, f"platform IN ({listing(values)})")


def upgrade():
    # 有 LinkedIn 資料列時拒絕升級，不替使用者刪資料；操作人需先評估與備份。
    bind = op.get_bind()
    for table, *_ in TABLES:
        if bind.scalar(sa.text(f"SELECT count(*) FROM {table} WHERE platform = 'linkedin'")):
            raise RuntimeError("Existing LinkedIn rows prevent removing the platform")
    for table, name, _, values in TABLES:
        replace(table, name, values)


def downgrade():
    # 只放寬平台清單，不改動任何資料列。
    for table, name, values, _ in TABLES:
        replace(table, name, values)
