from __future__ import annotations

import argparse
import json

from darius_api.config import Settings
from darius_api.providers import ComfyMcpProvider
from darius_api.workflows import WorkflowRegistry


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a registered workflow; does not submit a render.")
    parser.add_argument("workflow_id", nargs="?", default="qwen-image-2-1-text-to-image")
    args = parser.parse_args()
    settings = Settings.from_env()
    registry = WorkflowRegistry(settings.workflow_definitions_dir)
    registry.load()
    contract = registry.get(args.workflow_id)
    result = ComfyMcpProvider(settings).validate_workflow(contract)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
