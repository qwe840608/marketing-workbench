"""Persist caption progress and guarded completion across page reloads."""

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("publish_posts", sa.Column("caption_job_json", sa.JSON(), nullable=False,
                                           server_default="{}"))


def downgrade():
    op.drop_column("publish_posts", "caption_job_json")
