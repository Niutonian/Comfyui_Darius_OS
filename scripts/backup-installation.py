"""Back up the configured SQLite database before installer migrations (app stopped)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

from darius_api.config import Settings


def backup(destination: Path) -> None:
    url = make_url(Settings.from_env().database_url)
    if url.get_backend_name() != "sqlite":
        raise RuntimeError("Back up the external database manually before updating; automatic backup supports SQLite only.")
    if not url.database or url.database == ":memory:":
        return
    if url.query:
        raise RuntimeError("Custom SQLite URI options require a manual backup before updating.")
    source = Path(url.database).resolve()
    if not source.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as current:
        with sqlite3.connect(destination / "darius.db") as saved:
            current.backup(saved)
            if saved.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise RuntimeError("Database backup integrity check failed; installation stopped.")
    print("Database backup verified.")


if __name__ == "__main__":
    backup(Path(sys.argv[1]))
