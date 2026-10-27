from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def resolve_graph_slot(graph: dict, slot: str) -> tuple[str, str]:
    """Resolve using actual graph keys: node IDs and input names may contain dots."""
    matches = []
    for node_id, node in graph.items():
        prefix = f"{node_id}."
        if isinstance(node, dict) and slot.startswith(prefix):
            field = slot[len(prefix):]
            if field in node.get("inputs", {}):
                matches.append((node_id, field))
    if len(matches) != 1:
        raise ValueError(f"Workflow slot {slot!r} is {'ambiguous' if matches else 'unknown'}")
    return matches[0]


class WorkflowMapping(BaseModel):
    slot: str = Field(min_length=1)


class WorkflowInput(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    type: Literal["string", "integer", "number", "boolean", "json", "asset:image", "asset:video"]
    required: bool = True
    description: str = ""
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None
    maps_to: WorkflowMapping


class WorkflowOutput(BaseModel):
    kind: Literal["image", "video", "audio"]
    count: int = Field(default=1, ge=1)


class RuntimeMapping(BaseModel):
    filename_prefix_slot: str
    api_format: bool = False
    format_slot: str | None = None
    format: str | None = None


class WorkflowContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    version: str
    capability: Literal[
        "text-to-image",
        "image-to-image",
        "text-to-video",
        "image-to-video",
        "video-to-video",
        "character-sheet",
        "face-consistency",
        "lip-sync",
    ]
    execution_provider: Literal["local-comfyui", "bfl"]
    workflow_reference: str
    required_inputs: list[WorkflowInput]
    output: WorkflowOutput
    runtime_mapping: RuntimeMapping
    model_dependencies: list[str] = Field(default_factory=list)
    source_asset_ids: list[str] = Field(default_factory=list)
    project_id: str | None = None
    origin_workflow_id: str | None = None
    generation_brief_id: str | None = None
    generation_task_id: str | None = None
    prompt_bindings: dict[str, str] = Field(default_factory=dict)
    output_node_ids: list[str] = Field(default_factory=list, max_length=64)
    internal_only: bool = False
    estimated_vram_gb: float | None = None
    estimated_cost: float | None = None
    requires_approval: bool = True
    enabled: bool = True

    @model_validator(mode="after")
    def unique_input_keys(self) -> "WorkflowContract":
        keys = [item.key for item in self.required_inputs]
        if len(keys) != len(set(keys)):
            raise ValueError("workflow input keys must be unique")
        return self

    def validate_inputs(self, supplied: dict[str, Any]) -> dict[str, Any]:
        definitions = {item.key: item for item in self.required_inputs}
        unknown = sorted(set(supplied) - set(definitions))
        if unknown:
            raise ValueError(f"unknown workflow inputs: {', '.join(unknown)}")

        result: dict[str, Any] = {}
        for key, definition in definitions.items():
            if key in supplied:
                value = supplied[key]
            elif definition.default is not None:
                value = definition.default
            elif definition.required:
                raise ValueError(f"missing required workflow input: {key}")
            else:
                continue

            if definition.type == "string" and not isinstance(value, str):
                raise ValueError(f"{key} must be a string")
            if definition.type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError(f"{key} must be an integer")
            if definition.type == "number" and (
                not isinstance(value, (int, float)) or isinstance(value, bool)
            ):
                raise ValueError(f"{key} must be a number")
            if definition.type == "boolean" and not isinstance(value, bool):
                raise ValueError(f"{key} must be a boolean")
            if definition.minimum is not None and value < definition.minimum:
                raise ValueError(f"{key} must be at least {definition.minimum:g}")
            if definition.maximum is not None and value > definition.maximum:
                raise ValueError(f"{key} must be at most {definition.maximum:g}")
            if definition.type == "string" and definition.required and not value.strip():
                raise ValueError(f"{key} cannot be empty")
            result[key] = value
        if self.id.startswith("bfl-flux-3-"):
            from .bfl_catalog import validate_inputs
            validate_inputs(self.id, result)
        return result

    def public_dict(self) -> dict[str, Any]:
        data = self.model_dump(exclude={"runtime_mapping", "model_dependencies", "origin_workflow_id", "generation_brief_id", "generation_task_id", "prompt_bindings", "internal_only"})
        for item in data["required_inputs"]:
            item.pop("maps_to", None)
        return data


class WorkflowRegistry:
    def __init__(self, definitions_dir: Path, workflow_roots: tuple[Path, ...] = (), *, include_bfl: bool = False):
        self.definitions_dir = definitions_dir
        self.include_bfl = include_bfl
        self.workflow_roots = tuple(root.resolve() for root in workflow_roots if root is not None)
        self._contracts: dict[str, WorkflowContract] = {}
        self.issues: list[dict[str, str]] = []
        self._definition_signature = None
        self._lock = threading.RLock()

    def _signature(self):
        return tuple((str(path), path.stat().st_mtime_ns, path.stat().st_size)
                     for path in sorted(self.definitions_dir.glob("*.json")) if path.is_file())

    def refresh(self):
        with self._lock:
            if self._signature() != self._definition_signature:
                self.load()

    def source_path(self, contract: WorkflowContract) -> Path | None:
        if not self.workflow_roots:
            path = Path(contract.workflow_reference)
            return path.resolve() if path.is_file() else None
        reference = Path(contract.workflow_reference)
        if reference.is_absolute():
            return reference.resolve() if reference.is_file() else None
        if ".." in reference.parts:
            return None
        for root in self.workflow_roots:
            resolved = (root / reference).resolve()
            if resolved.is_relative_to(root) and resolved.is_file():
                return resolved
        return None

    def _source_exists(self, contract: WorkflowContract) -> bool:
        if contract.execution_provider == "bfl":
            return True
        if not self.workflow_roots:
            return True
        return self.source_path(contract) is not None

    def load(self) -> None:
        signature = self._signature()
        contracts: dict[str, WorkflowContract] = {}
        issues = []
        duplicates = set()
        for path in sorted(self.definitions_dir.glob("*.json")):
            try:
                contract = WorkflowContract.model_validate_json(path.read_text(encoding="utf-8-sig"))
            except (ValueError, OSError):
                issues.append({"file": path.name, "error": "Invalid workflow definition; fix its JSON/schema to enable it"})
                continue
            source = self.source_path(contract)
            if source is not None and source != Path(contract.workflow_reference):
                contract = contract.model_copy(update={"workflow_reference": str(source)})
            if contract.id in contracts or contract.id in duplicates:
                duplicates.add(contract.id)
                contracts.pop(contract.id, None)
                issues.append({"file": path.name, "error": f"Duplicate workflow id {contract.id!r}; both definitions disabled"})
                continue
            contracts[contract.id] = contract
        if self.include_bfl:
            from .bfl_catalog import contracts as cloud_contracts
            for contract in cloud_contracts():
                contracts.setdefault(contract.id, contract)
        self._contracts = contracts
        self.issues = issues
        self._definition_signature = signature
        for issue in issues:
            logging.getLogger(__name__).warning("Workflow unavailable: %s: %s", issue["file"], issue["error"])

    def get(self, workflow_id: str) -> WorkflowContract:
        self.refresh()
        try:
            contract = self._contracts[workflow_id]
        except KeyError as exc:
            raise KeyError(f"unknown workflow {workflow_id!r}") from exc
        if not self._source_exists(contract):
            raise KeyError(f"workflow {workflow_id!r} references a missing source file")
        return contract

    def enabled(self, *, include_internal: bool = False) -> list[WorkflowContract]:
        self.refresh()
        return [contract for contract in self._contracts.values()
                if contract.enabled and (include_internal or not contract.internal_only) and self._source_exists(contract)]

    def add(self, contract: WorkflowContract) -> None:
        """Publish a new immutable definition atomically for this API and its worker."""
        if contract.id in self._contracts:
            raise ValueError("workflow already exists")
        target = self.definitions_dir / f"{contract.id}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(contract.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(target)
        self._contracts = {**self._contracts, contract.id: contract}
        self.load()

    def serialized(self, contract: WorkflowContract) -> dict[str, Any]:
        return json.loads(contract.model_dump_json())
