"""Instagram Reels cover: allow the cover publish media role."""

import sqlalchemy as sa
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade():
    # 只放寬用途清單，不改動任何既有資料列。
    with op.batch_alter_table("publish_media") as batch:
        batch.drop_constraint(op.f("ck_publish_media_role"), type_="check")
        batch.create_check_constraint("role", "role IN ('media','thumbnail','cover')")


def downgrade():
    # 舊 schema 不容許封面；有資料時禁止降版，操作人需先評估與備份。
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT count(*) FROM publish_media WHERE role='cover'")):
        raise RuntimeError("Existing Instagram covers prevent downgrade")
    with op.batch_alter_table("publish_media") as batch:
        batch.drop_constraint(op.f("ck_publish_media_role"), type_="check")
        batch.create_check_constraint("role", "role IN ('media','thumbnail')")
