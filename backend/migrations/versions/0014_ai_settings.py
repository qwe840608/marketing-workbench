"""Encrypted global provider keys and versioned two-layer prompts."""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None
INITIAL_PROMPT = (
    "你是行銷管理工作檯的客服草稿助手。使用繁體中文與全形標點（，。！？：；「」）。"
    "回覆清楚、親切，依品牌指示回答；不確定的事項交由專人確認。"
)


def timestamps():
    return [
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    ]


def upgrade():
    op.create_table(
        "ai_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        *timestamps(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False, unique=True),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
    )
    op.create_table(
        "ai_key_verifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        *timestamps(),
        sa.Column("receipt_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("staff_id", sa.Integer(), sa.ForeignKey("staff.id"), nullable=False),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.String(32), nullable=False),
    )
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        *timestamps(),
        sa.Column("scope", sa.String(80), nullable=False),
        sa.Column("task", sa.String(40), nullable=False),
        sa.Column("brand_id", sa.Integer(), sa.ForeignKey("brands.id")),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("restored_from", sa.Integer()),
        sa.UniqueConstraint("scope", "task", "revision"),
    )
    db = op.get_bind()
    now = datetime.now(UTC).isoformat(timespec="microseconds")
    table = sa.Table("prompt_versions", sa.MetaData(), autoload_with=db)
    initial = dict(
        task="draft", revision=1, actor="system:migration:0014", created_at=now, updated_at=now
    )
    db.execute(table.insert().values(**initial, scope="shared", content=INITIAL_PROMPT))
    for brand in db.execute(sa.text("SELECT id, rules FROM brands")).mappings():
        db.execute(
            table.insert().values(
                **initial,
                scope=f"brand:{brand['id']}",
                brand_id=brand["id"],
                content=brand["rules"],
            )
        )
    op.execute("ALTER TABLE brands DROP COLUMN rules")


def downgrade():
    db = op.get_bind()
    if (
        db.execute(sa.text("SELECT count(*) FROM ai_credentials")).scalar()
        or db.execute(sa.text("SELECT count(*) FROM prompt_versions WHERE revision > 1")).scalar()
    ):
        raise RuntimeError("已有 AI 設定或 prompt 歷史，請以升級前備份隔離還原")
    op.add_column("brands", sa.Column("rules", sa.Text(), nullable=False, server_default=""))
    op.execute(
        "UPDATE brands SET rules = COALESCE((SELECT content FROM prompt_versions "
        "WHERE brand_id = brands.id AND task = 'draft' ORDER BY revision DESC LIMIT 1), '')"
    )
    op.drop_table("prompt_versions")
    op.drop_table("ai_key_verifications")
    op.drop_table("ai_credentials")
