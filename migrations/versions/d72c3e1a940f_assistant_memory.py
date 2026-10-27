"""Persist editable project context."""
from alembic import op
import sqlalchemy as sa

revision = "d72c3e1a940f"
down_revision = "c4b28f6e910a"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("assistant_memory"):
        return
    op.create_table("assistant_memory",
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("context_json", sa.JSON(), nullable=False))


def downgrade():
    op.drop_table("assistant_memory")
