from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from darius_api.main import app  # noqa: E402

OUTPUT = ROOT / "docs" / "openapi" / "darius-api.json"


def rendered_schema() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export or verify the committed FastAPI OpenAPI contract.")
    parser.add_argument("--check", action="store_true", help="Fail when the committed schema differs from FastAPI.")
    args = parser.parse_args()
    rendered = rendered_schema()
    if args.check:
        if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print(f"OpenAPI contract is stale: run {Path(__file__).name}", file=sys.stderr)
            return 1
        print(f"OpenAPI contract is current: {OUTPUT.relative_to(ROOT)}")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
