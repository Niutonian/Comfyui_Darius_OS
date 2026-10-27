"""Persist shot reference and take links."""
from alembic import op
import sqlalchemy as sa
revision = "e83d4f2b051a"
down_revision = "d72c3e1a940f"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("shot_production"):
        op.create_table("shot_production",
            sa.Column("shot_id", sa.String(36), sa.ForeignKey("shots.id"), primary_key=True),
            sa.Column("links_json", sa.JSON(), nullable=False))


def downgrade():
    op.drop_table("shot_production")
