from pathlib import Path

import pytest

from darius_api.workflows import WorkflowRegistry


def registry() -> WorkflowRegistry:
    root = Path(__file__).resolve().parents[1] / "workflows" / "definitions"
    value = WorkflowRegistry(root)
    value.load()
    return value


def test_contract_normalizes_defaults_and_hides_slot_mappings() -> None:
    contract = registry().get("minimax-h3-seamless-core")

    inputs = contract.validate_inputs({"script": "A single approved test shot."})

    assert inputs == {"script": "A single approved test shot.", "frames_per_shot": 192, "steps": 14}
    public = contract.public_dict()
    assert "runtime_mapping" not in public
    assert all("maps_to" not in item for item in public["required_inputs"])


def test_contract_rejects_unknown_and_out_of_range_inputs() -> None:
    contract = registry().get("minimax-h3-seamless-core")

    with pytest.raises(ValueError, match="unknown workflow inputs"):
        contract.validate_inputs({"script": "shot", "node_8": "unsafe"})
    with pytest.raises(ValueError, match="at least 48"):
        contract.validate_inputs({"script": "shot", "frames_per_shot": 1})



def test_krea_text_to_image_contract_is_registered_with_semantic_inputs() -> None:
    contract = registry().get("krea2-turbo-text-to-image")

    inputs = contract.validate_inputs({"prompt": "A quiet portrait in window light."})

    assert contract.capability == "text-to-image"
    assert contract.output.kind == "image"
    assert contract.execution_provider == "local-comfyui"
    assert inputs == {
        "prompt": "A quiet portrait in window light.",
        "refine_prompt": True,
        "aspect_ratio": "1:1 (Square)",
    }
    assert all("maps_to" not in item for item in contract.public_dict()["required_inputs"])


def test_enabled_workflows_excludes_missing_sources_without_deleting_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    definitions = root / "workflows" / "definitions"
    value = WorkflowRegistry(definitions, (root / "workflows" / "defaults", definitions))
    value.load()

    enabled_ids = {contract.id for contract in value.enabled()}

    assert "qwen-image-2-1-text-to-image" in enabled_ids
    assert "krea2-turbo-text-to-image" not in enabled_ids
    assert "minimax-h3-seamless-core" not in enabled_ids
    with pytest.raises(KeyError, match="missing source file"):
        value.get("krea2-turbo-text-to-image")
