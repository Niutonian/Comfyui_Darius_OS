from __future__ import annotations

from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import make_url

from darius_api.config import Settings
from darius_api.database import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    overrides = context.get_x_argument(as_dictionary=True)
    return overrides.get("database_url") or config.get_main_option("sqlalchemy.url") or Settings.from_env().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(), target_metadata=target_metadata, literal_binds=True,
        dialect_opts={"paramstyle": "named"}, compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    values = config.get_section(config.config_ini_section, {})
    values["sqlalchemy.url"] = database_url()
    url = make_url(values["sqlalchemy.url"])
    if url.get_backend_name() == "sqlite" and url.database and url.database != ":memory:" and not url.database.startswith("file:"):
        Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    connectable = engine_from_config(values, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
