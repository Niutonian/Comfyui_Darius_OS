"""Preserve unsigned 64-bit Canvas seeds as decimal text."""
from alembic import op
import sqlalchemy as sa

revision = "d38f9c705a6f"
down_revision = "c27e8b6f495e"
branch_labels = depends_on = None


def upgrade():
    for table, nullable in (("canvas_generations", False), ("generation_records", True)):
        columns = {c["name"]: c for c in sa.inspect(op.get_bind()).get_columns(table)}
        if not isinstance(columns["seed"]["type"], sa.String):
            with op.batch_alter_table(table) as batch:
                batch.alter_column("seed", existing_type=sa.Integer(), type_=sa.String(20), existing_nullable=nullable)


def downgrade():
    # Refuse a lossy rollback after large-seed generations have been created.
    for table, nullable in (("canvas_generations", False), ("generation_records", True)):
        values = op.get_bind().execute(sa.text(f"SELECT seed FROM {table} WHERE seed IS NOT NULL")).scalars()
        if any(int(v) > 2**63-1 for v in values):
            raise RuntimeError("Unsigned Canvas seeds cannot be represented by the old integer schema")
    for table, nullable in (("canvas_generations", False), ("generation_records", True)):
        with op.batch_alter_table(table) as batch:
            batch.alter_column("seed", existing_type=sa.String(20), type_=sa.Integer(), existing_nullable=nullable)
