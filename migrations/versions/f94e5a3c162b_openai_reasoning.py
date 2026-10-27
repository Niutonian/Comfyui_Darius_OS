"""Persist OpenAI thinking preference without changing the selected model."""
from alembic import op
import sqlalchemy as sa

revision = "f94e5a3c162b"
down_revision = "e83d4f2b051a"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("llm_preferences") and "reasoning_effort" not in {column["name"] for column in inspector.get_columns("llm_preferences")}:
        op.add_column("llm_preferences", sa.Column("reasoning_effort", sa.String(20), nullable=False, server_default="auto"))


def downgrade():
    op.drop_column("llm_preferences", "reasoning_effort")
