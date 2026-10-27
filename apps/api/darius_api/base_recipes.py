"""Folder-owned base recipes, never graphs generated for a previous request."""
from dataclasses import dataclass, field
from .workflow_catalog import discover_workflows
from .workflows import WorkflowInput, WorkflowOutput


@dataclass
class FolderRecipe:
    id: str
    name: str
    capability: str
    output: WorkflowOutput
    required_inputs: list = field(default_factory=list)
    execution_provider: str = "local-comfyui"
    version: str = "folder"
    project_id: str | None = None
    source_asset_ids: list = field(default_factory=list)
    origin_workflow_id: str | None = None
    input_hints: dict = field(default_factory=dict)
    registration: dict = field(default_factory=dict)

    @property
    def assignable_purposes(self):
        # A user's routing label is not a graph certification. Multi-mode video
        # templates often contain optional/bypassed image and video branches.
        if self.output.kind == "video":
            return ["text-to-video", "image-to-video", "video-to-video"]
        if self.capability == "text-to-image":
            return ["text-to-image", "character-sheet"]
        return ["image-to-image", "image-upscale", "face-consistency"]

    def public_dict(self):
        return {"id": self.id, "name": self.name, "capability": self.capability,
                "execution_provider": self.execution_provider, "version": self.version,
                "workflow_reference": self.id, "output": self.output.model_dump(),
                "required_inputs": [item.model_dump() for item in self.required_inputs],
                "estimated_vram_gb": None, "estimated_cost": None, "requires_approval": True,
                "enabled": True, "source": "defaults",
                "assignable_purposes": self.assignable_purposes, "input_hints": self.input_hints, "registration": self.registration}


def recipes(settings, registry):
    result = {}
    from .workflow_registration import public_registration
    for kind in ("image", "video"):
        for item in discover_workflows(settings, output_kind=kind, source_kind="none", limit=500)["workflows"]:
            needs_image = item["accepts_images_hint"]
            purpose = ("image-to-video" if needs_image else "text-to-video") if kind == "video" else ("image-to-image" if needs_image else "text-to-image")
            inputs = [WorkflowInput(key="image", type="asset:image", maps_to={"slot": "inspect-required.image"})] if needs_image else []
            result[item["workflow_id"]] = FolderRecipe(item["workflow_id"], item["name"], purpose, WorkflowOutput(kind=kind), inputs,
                input_hints={"image": needs_image, "video": item.get("accepts_video_hint", False)},
                registration=public_registration(settings, item["workflow_id"]))
    # Cloud recipes are reusable operations, not generated local drafts.
    for contract in registry.enabled():
        if contract.execution_provider == "bfl":
            result[contract.id] = contract
    return result
