"""Semantic config fingerprint (config_sha).

A SHA-256 hash over the recipe-only fields of a KilnConfig, deliberately
excluding eval/gate policy.  This means:

  - Changing a threshold (eval:) does NOT invalidate prior evidence.
  - Changing any recipe field (model, data, training, serve, output) DOES
    produce a new fingerprint.

The fingerprint is stamped on eval-gate evidence so stale/mismatched
evidence can be rejected.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from kiln.config.schema import KilnConfig


def recipe_hash(config: KilnConfig | dict) -> str:
    """Compute SHA-256 of the recipe portion of a config.

    Accepts either a validated KilnConfig or a raw dict (e.g. from
    yaml.safe_load before validation).  Keys are sorted for stability.

    Both paths go through Pydantic validation so defaults are always
    included identically — raw dict and validated model produce the same hash.
    """
    if isinstance(config, KilnConfig):
        recipe_dict = config.recipe.model_dump(mode="json")
    else:
        # Validate through Pydantic so defaults are injected consistently
        full = KilnConfig.model_validate({
            "recipe": config.get("recipe", {}),
            "eval": config.get("eval", {}),
        })
        recipe_dict = full.recipe.model_dump(mode="json")
    canonical = json.dumps(recipe_dict, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def config_sha_from_file(path: str | Path) -> str:
    """Load a kiln.yaml and return its recipe-only SHA-256 fingerprint."""
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"config root must be a YAML mapping, got {type(raw).__name__}")
    return recipe_hash(raw)


def verify_config_sha(config: KilnConfig, expected_sha: str) -> bool:
    """Check that a config matches an expected fingerprint."""
    return recipe_hash(config) == expected_sha
