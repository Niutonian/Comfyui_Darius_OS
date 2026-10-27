"""Stable offline contracts for job lifecycle tests, independent of live workflow files."""
import json
from pathlib import Path


def offline_definitions(tmp_path):
    target = tmp_path / "offline-definitions"
    target.mkdir(exist_ok=True)
    source = Path(__file__).resolve().parents[1] / "workflows" / "definitions"
    for path in source.glob("*.json"):
        contract = json.loads(path.read_text(encoding="utf-8"))
        # Only fake providers execute these contracts. No ComfyUI model or graph is needed.
        fixture = target / "graphs" / (contract["id"] + ".json")
        fixture.parent.mkdir(exist_ok=True)
        fixture.write_text('{"offline_test_fixture":true}', encoding="utf-8")
        contract["workflow_reference"] = str(fixture)
        contract["runtime_mapping"]["api_format"] = False
        (target / path.name).write_text(json.dumps(contract), encoding="utf-8")
    return target
