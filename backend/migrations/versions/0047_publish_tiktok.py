"""TikTok publishing: allow the tiktok publish target platform (videos sent to the inbox)."""

import sqlalchemy as sa
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade():
    # 只放寬平台清單，不改動任何既有資料列。
    with op.batch_alter_table("publish_targets") as batch:
        batch.drop_constraint(op.f("ck_publish_targets_platform"), type_="check")
        batch.create_check_constraint(
            "platform", "platform IN ('facebook','instagram','threads','youtube','tiktok')"
        )


def downgrade():
    # 舊 schema 不容許 TikTok 目標；有資料時禁止降版，操作人需先評估與備份。
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT count(*) FROM publish_targets WHERE platform='tiktok'")):
        raise RuntimeError("Existing TikTok publications prevent downgrade")
    with op.batch_alter_table("publish_targets") as batch:
        batch.drop_constraint(op.f("ck_publish_targets_platform"), type_="check")
        batch.create_check_constraint(
            "platform", "platform IN ('facebook','instagram','threads','youtube')"
        )
