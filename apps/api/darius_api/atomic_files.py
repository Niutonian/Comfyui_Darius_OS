"""Atomic JSON replacement using inherited directory permissions on Windows."""
import json
import os
from pathlib import Path
import time
from uuid import uuid4


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(3):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt == 2:
                    raise
                time.sleep(0.03)
    finally:
        temporary.unlink(missing_ok=True)
