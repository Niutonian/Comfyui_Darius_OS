"""Provider-independent, immutable Canvas content and deterministic geometry."""
from __future__ import annotations

import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PRESETS = {
    "square": ("1:1 (Square)", 1, 1),
    "poster": ("2:3 (Portrait Photo)", 2, 3),
    "photo": ("3:2 (Photo)", 3, 2),
    "portrait": ("3:4 (Portrait Standard)", 3, 4),
    "standard": ("4:3 (Standard)", 4, 3),
    "vertical": ("9:16 (Portrait Widescreen)", 9, 16),
    "wide": ("16:9 (Widescreen)", 16, 9),
    "ultrawide": ("21:9 (Ultrawide)", 21, 9),
}


def dimensions(preset):
    if preset not in PRESETS:
        raise ValueError("Choose a supported 1 MP Canvas preset")
    _, w, h = PRESETS[preset]
    scale = math.sqrt(1024 * 1024 / (w * h))
    # Verified against ComfyUI 0.42.4 ResolutionSelector (ties-to-even round).
    return round(w * scale / 16) * 16, round(h * scale / 16) * 16


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Artboard(StrictModel):
    preset: str = "square"
    width: int = Field(default=1024, ge=64, le=2048)
    height: int = Field(default=1024, ge=64, le=2048)

    @model_validator(mode="after")
    def supported(self):
        if (self.width, self.height) != dimensions(self.preset):
            raise ValueError("Artboard dimensions must match the selected 1 MP preset")
        return self


class CanvasRegion(StrictModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    parentId: str | None = Field(default=None, max_length=80)
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["group", "object", "character", "text"] = "object"
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)
    order: int = Field(default=0, ge=0, le=10000)
    description: str = Field(default="", max_length=2000)
    text: str = Field(default="", max_length=2000)
    palette: list[str] = Field(default_factory=list, max_length=5)
    visible: bool = True
    locked: bool = False

    @model_validator(mode="after")
    def contained(self):
        if self.x + self.width > 1 + 1e-9 or self.y + self.height > 1 + 1e-9:
            raise ValueError("A region must remain inside its parent")
        if any(not re.fullmatch(r"#[0-9a-fA-F]{6}", color) for color in self.palette):
            raise ValueError("Palette colours must be six-digit hex values, such as #d4a574")
        return self


class CanvasContent(StrictModel):
    schemaVersion: Literal[1] = 1
    name: str = Field(default="Untitled canvas", min_length=1, max_length=200)
    artboard: Artboard = Field(default_factory=Artboard)
    globalPrompt: str = Field(default="", max_length=6000)
    regions: list[CanvasRegion] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def hierarchy(self):
        by_id = {r.id: r for r in self.regions}
        if len(by_id) != len(self.regions):
            raise ValueError("Region IDs must be unique")
        for region in self.regions:
            seen, current = set(), region
            while current is not None:
                if current.id in seen:
                    raise ValueError("Region hierarchy contains a cycle")
                seen.add(current.id)
                if len(seen) > 12:
                    raise ValueError("Canvas hierarchy is limited to 12 levels")
                if current.parentId is not None and current.parentId not in by_id:
                    raise ValueError("Region parent is missing")
                current = by_id.get(current.parentId)
        if sum(len(r.description) + len(r.text) for r in self.regions) > 24000:
            raise ValueError("Canvas region text is limited to 24,000 characters in total")
        return self


def resolve_regions(content: CanvasContent):
    """Stable tree order; parent-local geometry never depends on editor zoom."""
    result = []
    children = {}
    for region in content.regions:
        children.setdefault(region.parentId, []).append(region)

    def visit(parent_id, bounds, hidden=False, locked=False, depth=0):
        px, py, pw, ph = bounds
        for region in sorted(children.get(parent_id, []), key=lambda r: (r.order, r.id)):
            rect = (px + region.x * pw, py + region.y * ph, region.width * pw, region.height * ph)
            is_hidden, is_locked = hidden or not region.visible, locked or region.locked
            result.append({"region": region, "rect": rect, "hidden": is_hidden, "locked": is_locked, "depth": depth})
            visit(region.id, rect, is_hidden, is_locked, depth + 1)

    visit(None, (0, 0, content.artboard.width, content.artboard.height))
    return result


def compile_regions(content, *, palettes=False):
    boxes, index_map, characters = [], [], []
    for resolved in resolve_regions(content):
        region = resolved["region"]
        if resolved["hidden"] or region.kind == "group":
            continue
        if region.palette and not palettes:
            raise ValueError("MOSS does not support palette fields; use descriptions or choose FIBO")
        if not region.description.strip() and region.kind != "text":
            raise ValueError(f"Describe the contents of {region.name} before generating")
        if region.kind == "text" and not region.text.strip():
            raise ValueError(f"Enter the exact text for {region.name}")
        x, y, w, h = resolved["rect"]
        if w < 1 or h < 1:
            raise ValueError(f"{region.name} is smaller than one output pixel")
        index_map.append(region.id)
        if region.kind == "character":
            # Installed MOSS indexes ALL rows, including text, from one.
            characters.append(str(len(index_map)))
        boxes.append({"x": x, "y": y, "width": w, "height": h,
            "metadata": {"type": "text" if region.kind == "text" else "obj", "text": region.text if region.kind == "text" else "",
                         "desc": region.description, "palette": list(region.palette) if palettes else []}})
    if not boxes and not content.globalPrompt.strip():
        raise ValueError("Describe the composition or add described regions before generating")
    return boxes, index_map, ", ".join(characters)
