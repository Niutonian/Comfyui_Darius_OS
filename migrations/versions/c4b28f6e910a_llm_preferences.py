"""Persist the selected conversational LLM provider and model."""
from alembic import op
import sqlalchemy as sa

revision = "c4b28f6e910a"
down_revision = "a8d134f02c11"
branch_labels = None
depends_on = None


def upgrade():
    # Local API startup may already have created this new table with create_all.
    if sa.inspect(op.get_bind()).has_table("llm_preferences"):
        return
    op.create_table(
        "llm_preferences",
        sa.Column("id", sa.String(20), primary_key=True),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("llm_preferences")
