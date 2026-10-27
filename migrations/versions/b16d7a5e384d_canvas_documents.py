"""Project-owned immutable Canvas revisions and generation receipts."""
from alembic import op
import sqlalchemy as sa

revision = "b16d7a5e384d"
down_revision = "a05f6b4d273c"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("canvas_documents"):
        op.create_table("canvas_documents",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("active_generation_id", sa.String(36), nullable=True),
            sa.Column("selection_version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))
        op.create_index("ix_canvas_documents_project_id", "canvas_documents", ["project_id"])
    if not sa.inspect(bind).has_table("canvas_revisions"):
        op.create_table("canvas_revisions",
            sa.Column("document_id", sa.String(36), sa.ForeignKey("canvas_documents.id"), primary_key=True),
            sa.Column("revision", sa.Integer(), primary_key=True),
            sa.Column("content_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    if not sa.inspect(bind).has_table("canvas_generations"):
        op.create_table("canvas_generations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("document_id", sa.String(36), sa.ForeignKey("canvas_documents.id"), nullable=False),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id"), unique=True, nullable=False),
            sa.Column("idempotency_key", sa.String(80), nullable=False),
            sa.Column("seed", sa.Integer(), nullable=False),
            sa.Column("selection_version", sa.Integer(), nullable=False),
            sa.Column("provenance_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("document_id", "idempotency_key", name="uq_canvas_request"))
        op.create_index("ix_canvas_generations_document_id", "canvas_generations", ["document_id"])


def downgrade():
    op.drop_table("canvas_generations")
    op.drop_table("canvas_revisions")
    op.drop_table("canvas_documents")
