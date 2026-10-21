"""Preserve immutable AI output for author-based send review."""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("drafts", sa.Column("original_text", sa.Text()))
    # Only unedited drafts have a known original; never fabricate lost revision history.
    op.execute("UPDATE drafts SET original_text = text WHERE version = 1")


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM drafts WHERE original_text IS NOT NULL "
                "AND original_text != text"
            )
        )
        .scalar()
    ):
        raise RuntimeError("不可刪除 AI 原文稽核資料")
    op.drop_column("drafts", "original_text")
