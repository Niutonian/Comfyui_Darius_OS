"""Upgrade synthetic previous-schema data; never open the workstation database."""
from pathlib import Path
from datetime import datetime
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, create_engine, inspect, text
from darius_api.database import Base

ROOT = Path(__file__).resolve().parents[1]


def configuration(tmp_path):
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", "sqlite:///" + (tmp_path / "upgrade.db").as_posix())
    return config


def test_previous_schema_upgrade_preserves_project_chat_and_large_seed(tmp_path):
    config = configuration(tmp_path)
    command.upgrade(config, "c27e8b6f495e")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    with engine.begin() as connection:
        # Use the historical schema's actual columns/default requirements.
        tables = MetaData()
        tables.reflect(bind=connection)
        stamp = datetime(2026, 1, 1)
        connection.execute(tables.tables["projects"].insert(), dict(id="synthetic-project", name="Moon garden", description="", creative_brief="", visual_style="", default_aspect_ratio="1:1", default_resolution="1024x1024", default_fps=24, settings_json={}, created_at=stamp, updated_at=stamp))
        connection.execute(tables.tables["conversations"].insert(), dict(id="synthetic-chat", project_id="synthetic-project", title="Ideas", created_at=stamp, updated_at=stamp))
        connection.execute(tables.tables["messages"].insert(), dict(id="synthetic-message", conversation_id="synthetic-chat", role="user", content="A moonlit garden", metadata_json={}, created_at=stamp))
        connection.execute(tables.tables["canvas_documents"].insert(), dict(id="synthetic-canvas", project_id="synthetic-project", name="Garden", revision=1, active_generation_id=None, selection_version=0, created_at=stamp, updated_at=stamp))
        connection.execute(tables.tables["canvas_revisions"].insert(), dict(document_id="synthetic-canvas", revision=1, content_json={"globalPrompt": "Glass flowers"}, created_at=stamp))
        connection.execute(tables.tables["moss_boards"].insert(), dict(id="synthetic-board", project_id="synthetic-project", document_id="synthetic-canvas", revision=1, settings_json={"adapterVersion": "fibo-fast-experimental-v1", "seed": 4294967295}, archived=False))
    command.upgrade(config, "head")
    command.upgrade(config, "head")  # Installer repair is safe to repeat.
    with engine.connect() as connection:
        assert connection.execute(text("SELECT name FROM projects")).scalar() == "Moon garden"
        assert connection.execute(text("SELECT content FROM messages")).scalar() == "A moonlit garden"
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == ScriptDirectory.from_config(config).get_current_head()
        import json
        settings = json.loads(connection.execute(text("SELECT settings_json FROM moss_boards")).scalar())
        assert settings["seed"] == 4294967295
        assert settings["adapterVersion"] == "fibo-fast-turbo-v2"
        assert json.loads(connection.execute(text("SELECT content_json FROM canvas_revisions")).scalar())["globalPrompt"] == "Glass flowers"
        assert connection.execute(text("PRAGMA integrity_check")).scalar() == "ok"
        assert not connection.execute(text("PRAGMA foreign_key_check")).fetchall()
        assert set(Base.metadata.tables) <= set(inspect(connection).get_table_names())
    engine.dispose()


def test_empty_install_migrates_and_matches_declared_columns(tmp_path):
    config = configuration(tmp_path)
    command.upgrade(config, "head")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    inspector = inspect(engine)
    for name, table in Base.metadata.tables.items():
        assert {column.name for column in table.columns} <= {column["name"] for column in inspector.get_columns(name)}, name
    engine.dispose()
