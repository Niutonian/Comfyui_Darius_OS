"""Select the user-requested Turbo profile for future fast previews."""
from alembic import op
import sqlalchemy as sa

revision = "e49a0d816b70"
down_revision = "d38f9c705a6f"
branch_labels = depends_on = None


def swap(old, new):
    boards = sa.table("moss_boards", sa.column("id", sa.String), sa.column("settings_json", sa.JSON), sa.column("revision", sa.Integer))
    bind = op.get_bind()
    for row in bind.execute(sa.select(boards)).mappings():
        settings = dict(row["settings_json"])
        if settings.get("adapterVersion") != old:
            continue
        remembered = dict(settings.get("providerSettings", {}))
        remembered.setdefault(old, {"seed": settings.get("seed")})
        settings.update(adapterVersion=new, providerSettings=remembered)
        bind.execute(boards.update().where(boards.c.id == row["id"]).values(settings_json=settings, revision=row["revision"]+1))


def upgrade():
    swap("fibo-fast-experimental-v1", "fibo-fast-turbo-v2")


def downgrade():
    swap("fibo-fast-turbo-v2", "fibo-fast-experimental-v1")
