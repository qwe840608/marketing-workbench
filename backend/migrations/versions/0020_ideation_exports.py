"""Persist report and script export results; leave existing content and accounts intact."""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("ideation_reports", "video_scripts"):
        op.add_column(
            table, sa.Column("export_json", sa.JSON(), nullable=False, server_default="{}")
        )


def downgrade():
    for table in ("ideation_reports", "video_scripts"):
        if (
            op.get_bind()
            .execute(sa.text(f"SELECT count(*) FROM {table} WHERE export_json != '{{}}' "))
            .scalar()
        ):
            raise RuntimeError("Export records prevent downgrade")
        op.drop_column(table, "export_json")
