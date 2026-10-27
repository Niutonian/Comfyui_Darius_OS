"""Persist application-wide base workflow defaults independently of projects."""
from alembic import op
import sqlalchemy as sa

revision = "a05f6b4d273c"
down_revision = "f94e5a3c162b"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("global_workflow_preferences"):
        op.create_table("global_workflow_preferences",
            sa.Column("id", sa.String(20), primary_key=True),
            sa.Column("preferences_json", sa.JSON(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("global_workflow_preferences")
