"""Retire comment jobs without changing messages or sending permissions."""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("window_start", "window_end", "stopped_at"):
        op.add_column("comment_polls", sa.Column(name, sa.String(32)))
    op.execute("""UPDATE comment_polls SET
        stopped_at = CASE WHEN requested_at IS NOT NULL OR run_id IS NOT NULL
            OR manual_requested = 1 OR progress_json != '{}' THEN CURRENT_TIMESTAMP END,
        manual_requested = 0, requested_at = NULL, run_id = NULL, lease_until = NULL,
        progress_json = '{}', last_error = NULL,
        backfill_completed_at = CASE WHEN backfill_id IS NOT NULL
            THEN COALESCE(backfill_completed_at, CURRENT_TIMESTAMP) END""")
    op.execute("""UPDATE comment_backfills SET discovery_completed_at =
        COALESCE(discovery_completed_at, CURRENT_TIMESTAMP)""")
    op.execute("""UPDATE settings SET value_json = '{}'
        WHERE key = 'scheduler.job.comments'""")


def downgrade():
    # Never resurrect retired work on downgrade.
    with op.batch_alter_table("comment_polls") as batch:
        for name in ("stopped_at", "window_end", "window_start"):
            batch.drop_column(name)
