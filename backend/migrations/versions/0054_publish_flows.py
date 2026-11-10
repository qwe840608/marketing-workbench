"""Publish flows: node-and-edge post scheduling that hands sending to publish."""

import sqlalchemy as sa
from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "publish_flows",
        sa.Column("brand_id", sa.Integer(), nullable=False),
        sa.Column("creator_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("graph_json", sa.JSON(), nullable=False),
        sa.Column("next_run_at", sa.String(32), nullable=True),
        sa.Column("deleted_at", sa.String(32), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(
            ["brand_id"], ["brands.id"], name=op.f("fk_publish_flows_brand_id_brands")
        ),
        sa.ForeignKeyConstraint(
            ["creator_id"], ["staff.id"], name=op.f("fk_publish_flows_creator_id_staff")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publish_flows")),
    )
    op.create_index(op.f("ix_publish_flows_brand_id"), "publish_flows", ["brand_id"])
    op.create_index(op.f("ix_publish_flows_next_run_at"), "publish_flows", ["next_run_at"])
    op.create_table(
        "publish_flow_runs",
        sa.Column("flow_id", sa.Integer(), nullable=False),
        sa.Column("brand_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("trigger_at", sa.String(32), nullable=False),
        sa.Column("graph_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("current_node", sa.String(40), nullable=True),
        sa.Column("draft_post_id", sa.Integer(), nullable=True),
        sa.Column("wake_at", sa.String(32), nullable=True),
        sa.Column("approval_deadline", sa.String(32), nullable=True),
        sa.Column("approved_at", sa.String(32), nullable=True),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("steps_json", sa.JSON(), nullable=False),
        sa.Column("error", sa.String(200), nullable=True),
        sa.Column("finished_at", sa.String(32), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.CheckConstraint(
            "status IN ('running','awaiting_approval','scheduled','done','partial','failed',"
            "'expired','cancelled','missed')",
            name=op.f("ck_publish_flow_runs_status"),
        ),
        sa.ForeignKeyConstraint(
            ["flow_id"],
            ["publish_flows.id"],
            name=op.f("fk_publish_flow_runs_flow_id_publish_flows"),
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"], ["brands.id"], name=op.f("fk_publish_flow_runs_brand_id_brands")
        ),
        sa.ForeignKeyConstraint(
            ["draft_post_id"],
            ["publish_posts.id"],
            name=op.f("fk_publish_flow_runs_draft_post_id_publish_posts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_publish_flow_runs")),
    )
    op.create_index(op.f("ix_publish_flow_runs_flow_id"), "publish_flow_runs", ["flow_id"])
    op.create_index(op.f("ix_publish_flow_runs_brand_id"), "publish_flow_runs", ["brand_id"])
    op.create_index(op.f("ix_publish_flow_runs_status"), "publish_flow_runs", ["status"])
    op.create_index(op.f("ix_publish_flow_runs_wake_at"), "publish_flow_runs", ["wake_at"])


def downgrade():
    op.drop_table("publish_flow_runs")
    op.drop_table("publish_flows")
