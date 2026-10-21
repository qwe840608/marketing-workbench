"""Stories format and per-story hourly/final insights; preserve existing posts."""

import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("publish_posts") as batch:
        batch.drop_constraint(op.f("ck_publish_posts_format"), type_="check")
        batch.create_check_constraint(
            "format", "format IN ('video','image','carousel','text','story')"
        )
    op.create_table(
        "publish_story_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("target_id", sa.Integer(), sa.ForeignKey("publish_targets.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("slot", sa.String(32), nullable=False),
        sa.Column("observed_at", sa.String(32), nullable=False),
        sa.Column("final", sa.Boolean(), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("target_id", "position", "slot"),
    )
    op.create_index(
        "ix_publish_story_snapshots_target_id", "publish_story_snapshots", ["target_id"]
    )


def downgrade():
    # 舊 schema 不容許 story；禁止降版遺失已建立的限動，操作人需先評估與備份。
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM publish_posts WHERE format='story'"))
    if count:
        raise RuntimeError("Existing stories prevent downgrade")
    op.drop_table("publish_story_snapshots")
    with op.batch_alter_table("publish_posts") as batch:
        batch.drop_constraint(op.f("ck_publish_posts_format"), type_="check")
        batch.create_check_constraint("format", "format IN ('video','image','carousel','text')")
