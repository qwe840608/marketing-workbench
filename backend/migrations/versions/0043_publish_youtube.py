"""YouTube publishing: thumbnail media role and the youtube publish target platform."""

import sqlalchemy as sa
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade():
    # 既有素材全部是一般素材；縮圖另以 role 區分，不改動任何既有資料列。
    with op.batch_alter_table("publish_media") as batch:
        batch.add_column(sa.Column("role", sa.String(16), nullable=False, server_default="media"))
        batch.create_check_constraint("role", "role IN ('media','thumbnail')")
    with op.batch_alter_table("publish_targets") as batch:
        batch.drop_constraint(op.f("ck_publish_targets_platform"), type_="check")
        batch.create_check_constraint(
            "platform", "platform IN ('facebook','instagram','threads','youtube')"
        )
    # Agent 上傳碼可指定這次上傳的是縮圖；既有上傳碼都是一般素材。
    op.add_column(
        "agent_uploads",
        sa.Column("role", sa.String(16), nullable=False, server_default="media"),
    )


def downgrade():
    # 舊 schema 不容許 YouTube 目標與縮圖；有資料時禁止降版，操作人需先評估與備份。
    bind = op.get_bind()
    youtube = bind.scalar(sa.text("SELECT count(*) FROM publish_targets WHERE platform='youtube'"))
    thumbnails = bind.scalar(sa.text("SELECT count(*) FROM publish_media WHERE role='thumbnail'"))
    if youtube or thumbnails:
        raise RuntimeError("Existing YouTube publications prevent downgrade")
    op.drop_column("agent_uploads", "role")
    with op.batch_alter_table("publish_targets") as batch:
        batch.drop_constraint(op.f("ck_publish_targets_platform"), type_="check")
        batch.create_check_constraint("platform", "platform IN ('facebook','instagram','threads')")
    with op.batch_alter_table("publish_media") as batch:
        batch.drop_constraint(op.f("ck_publish_media_role"), type_="check")
        batch.drop_column("role")
