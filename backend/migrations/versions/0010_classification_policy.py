"""無文字政策分流不冒充模型呼叫。"""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("classifications") as batch:
        batch.drop_constraint(op.f("ck_classifications_classification_engine"), type_="check")
        batch.create_check_constraint(
            "classification_engine", "engine IN ('jev', 'keyword', 'policy')"
        )
    op.execute("UPDATE classifications SET action='skip' WHERE action='ignore'")


def downgrade():
    op.execute("UPDATE classifications SET engine='keyword' WHERE engine='policy'")
    op.execute("UPDATE classifications SET action='ignore' WHERE action='skip'")
    with op.batch_alter_table("classifications") as batch:
        batch.drop_constraint(op.f("ck_classifications_classification_engine"), type_="check")
        batch.create_check_constraint("classification_engine", "engine IN ('jev', 'keyword')")
