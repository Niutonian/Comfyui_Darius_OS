"""One project workspace, one editable owner per MOSS document."""
from alembic import op
import sqlalchemy as sa

revision = "c27e8b6f495e"
down_revision = "b16d7a5e384d"
branch_labels = depends_on = None


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("canvas_workspaces"):
        op.create_table("canvas_workspaces",
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), primary_key=True),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("schema_version", sa.Integer(), nullable=False),
            sa.Column("placements_json", sa.JSON(), nullable=False))
    if not sa.inspect(bind).has_table("moss_boards"):
        op.create_table("moss_boards",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("document_id", sa.String(36), sa.ForeignKey("canvas_documents.id"), unique=True, nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("settings_json", sa.JSON(), nullable=False),
            sa.Column("archived", sa.Boolean(), nullable=False))
        op.create_index("ix_moss_boards_project_id", "moss_boards", ["project_id"])


def downgrade():
    op.drop_table("moss_boards")
    op.drop_table("canvas_workspaces")
