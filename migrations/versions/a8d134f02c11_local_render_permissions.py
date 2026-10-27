"""Persist per-project local rendering permission."""
from alembic import op
import sqlalchemy as sa

revision = "a8d134f02c11"
down_revision = "879a97ae7905"
branch_labels = None
depends_on = None


def upgrade():
    # Local API startup may already have created this new table with create_all.
    if sa.inspect(op.get_bind()).has_table("local_render_permissions"):
        return
    op.create_table("local_render_permissions",
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False))


def downgrade():
    op.drop_table("local_render_permissions")
