"""V2 recipe catalog — named, reusable training recipes (V1 recipe surface).

Recipes are small, validated descriptors kept in `specs/recipes/catalog.json`.
The CLI `recipe list` / `recipe get` read from here; a recipe can be expanded into
a `TrainingConfig` so users don't hand-write hyperparameters.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[3] / "specs" / "recipes" / "catalog.json"

VALID_KINDS = {"sft", "dpo"}


@dataclass(frozen=True)
class Recipe:
    name: str
    kind: str
    model: str
    dataset: str
    epochs: int
    lr: float
    layer_streaming: bool = False
    quantization: str = "4bit"


def _coerce(raw: dict) -> Recipe:
    if raw.get("kind") not in VALID_KINDS:
        raise ValueError(f"recipe {raw.get('name')!r} has invalid kind {raw.get('kind')!r}")
    return Recipe(
        name=raw["name"],
        kind=raw["kind"],
        model=raw.get("model", "auto"),
        dataset=raw.get("dataset", "auto"),
        epochs=int(raw.get("epochs", 3)),
        lr=float(raw.get("lr", 2e-5)),
        layer_streaming=bool(raw.get("layer_streaming", False)),
        quantization=raw.get("quantization", "4bit"),
    )


def load_catalog(path: Path | None = None) -> list[Recipe]:
    p = path or CATALOG_PATH
    data = json.loads(p.read_text())
    return [_coerce(r) for r in data]


def get(name: str, path: Path | None = None) -> Recipe:
    for r in load_catalog(path):
        if r.name == name:
            return r
    raise KeyError(f"recipe {name!r} not in catalog")


def names(path: Path | None = None) -> list[str]:
    return [r.name for r in load_catalog(path)]
