"""Notes and frames on the project canvas."""
from alembic import op
import sqlalchemy as sa

revision = "a7c41e9d2b30"
down_revision = "e49a0d816b70"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("canvas_workspaces") and "annotations_json" not in {column["name"] for column in inspector.get_columns("canvas_workspaces")}:
        op.add_column("canvas_workspaces", sa.Column("annotations_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))


def downgrade():
    op.drop_column("canvas_workspaces", "annotations_json")
