"""Kiln configuration — Pydantic v2 single source of truth.

Layout rule (locked): recipe fields and eval/gate policy fields are separated
at the TOP LEVEL of the document:

    recipe:
      model: ...
      data: ...
      training: ...
      serve: ...
      output: ...
    eval:
      ship: ...

so semantic config fingerprints (config_sha) can hash the recipe only,
excluding policy that does not affect model weights.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Bounds are imported from the runtime modules that enforce them where they
# exist; pure-schema bounds are declared here once and referenced by tests.


class ModelConfig(BaseModel):
    """Which base model this config targets."""

    base: str = Field(..., min_length=1, description="HF repo id or local path of the base model")
    arch: str | None = Field(None, description="Architecture override; auto-detected when omitted")


class DataConfig(BaseModel):
    """Training data location and format."""

    train: Path
    format: str = Field("auto", description="auto|alpaca|chatml|sharegpt|plain")
    val_split: float = Field(0.1, ge=0.0, lt=1.0)

    @field_validator("format")
    @classmethod
    def _known_format(cls, v: str) -> str:
        allowed = {"auto", "alpaca", "chatml", "sharegpt", "plain"}
        if v not in allowed:
            raise ValueError(f"data.format must be one of {sorted(allowed)}, got {v!r}")
        return v


class LoraConfig(BaseModel):
    r: int = Field(16, ge=1, le=256)
    alpha: int = Field(16, ge=1, le=512)
    dropout: float = Field(0.05, ge=0.0, lt=1.0)

    # Cross-field legality gate: alpha conventionally >= r.
    # Pydantic v2 model_validator would be used with more fields; kept simple here.


class TrainingConfig(BaseModel):
    epochs: int = Field(3, ge=1, le=100)
    lr: float = Field(2e-5, gt=0.0, le=1.0)
    batch_size: int | str = Field(4, description="int or 'auto'")
    lora: LoraConfig = Field(default_factory=LoraConfig)
    quantization: str = Field("4bit", description="none|4bit")
    seed: int = Field(1234)

    @field_validator("batch_size")
    @classmethod
    def _batch_size_shape(cls, v: int | str) -> int | str:
        if isinstance(v, str) and v != "auto":
            raise ValueError('training.batch_size must be an integer or "auto"')
        if isinstance(v, int) and v < 1:
            raise ValueError("training.batch_size must be >= 1")
        return v

    @field_validator("quantization")
    @classmethod
    def _known_quant(cls, v: str) -> str:
        allowed = {"none", "4bit"}
        if v not in allowed:
            raise ValueError(f"training.quantization must be one of {sorted(allowed)}, got {v!r}")
        return v


class ServeConfig(BaseModel):
    host: str = Field("127.0.0.1", description="localhost bind by default (security default)")
    port: int = Field(8000, ge=1, le=65535)
    context_length: int = Field(4096, ge=256)


class OutputConfig(BaseModel):
    dir: Path = Field(Path("./output"))


class RecipeConfig(BaseModel):
    """Everything that affects what weights come out / how they are served."""

    model_config = ConfigDict(extra="forbid")

    model: ModelConfig
    data: DataConfig | None = None
    training: TrainingConfig = Field(default_factory=TrainingConfig)
    serve: ServeConfig = Field(default_factory=ServeConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)


class ShipGatePolicy(BaseModel):
    """Eval-gate policy. Deliberately separate from recipe: loosening a
    threshold must never invalidate evidence about unchanged weights."""

    metric_threshold: float = Field(0.0, description="min task-metric win vs base")


class EvalPolicyConfig(BaseModel):
    """Eval/gate policy block (top-level `eval:`). Excluded from config_sha."""

    model_config = ConfigDict(extra="forbid")

    ship: ShipGatePolicy = Field(default_factory=ShipGatePolicy)


class KilnConfig(BaseModel):
    """Root config schema. Single source of truth for every kiln.yaml field."""

    model_config = ConfigDict(extra="forbid")

    recipe: RecipeConfig
    eval: EvalPolicyConfig = Field(default_factory=EvalPolicyConfig)


def load_config(path: str | Path) -> KilnConfig:
    """Load and validate a kiln.yaml file."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"config file not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"config root must be a YAML mapping, got {type(raw).__name__}")
    return KilnConfig.model_validate(raw)


def config_to_yaml(config: KilnConfig) -> str:
    """Serialize a config back to canonical YAML (round-trip guarantee)."""
    return yaml.safe_dump(
        config.model_dump(mode="json"),
        sort_keys=False,
        allow_unicode=True,
    )
