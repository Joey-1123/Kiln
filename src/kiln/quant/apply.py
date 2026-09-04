"""Torch-free quantization application spec + lazy loader-config resolution.

The control plane (CLI, gateway, trainer) builds :class:`QuantSpec` and validates
scheme names without importing torch.  The actual transformers quantization config
is resolved lazily inside :func:`resolve_load_quant_config` /
:func:`resolve_training_quant_config`, which import torch/transformers only when a
model is actually being loaded or trained.

Per the reference best-practice (Soup/FreeToken/colibri): the machinery stays
format-agnostic and never trusts a quant — correctness is gated independently by the
parity oracle.
"""

from __future__ import annotations

from dataclasses import dataclass

from kiln.quant import QUANTIZE_SCHEMES, SCHEMES, VALID_NAMES, QuantScheme
from kiln.utils.errors import KilnError
from kiln.utils.exitcodes import USAGE


@dataclass(frozen=True)
class QuantSpec:
    name: str
    bits: int
    backend: str  # "cuda" | "roc" | "cpu"
    applied_at: str  # "load" | "train" | "artifact"


def build_quant_spec(name: str) -> QuantSpec:
    """Validate a scheme name (torch-free) and return its spec.

    Raises KilnError (mapped to a friendly USAGE error) on an unknown name.
    """
    if name not in VALID_NAMES:
        raise KilnError(
            message=f"Unknown quantization scheme {name!r}.",
            hint=f"Choose from: {', '.join(sorted(VALID_NAMES))}",
            exit_code=USAGE,
        )
    s: QuantScheme = SCHEMES[name]
    if name in QUANTIZE_SCHEMES:
        applied = "artifact"
    elif name in ("4bit", "8bit"):
        applied = "train"
    else:
        applied = "load"
    return QuantSpec(name=name, bits=s.bits, backend=s.backend, applied_at=applied)


def resolve_load_quant_config(spec: QuantSpec):
    """Return a transformers ``quantization_config`` for the serve/load path.

    Supports none/4bit/8bit.  ``gptq``/``awq`` are pre-quantized artifacts that
    carry their own config in ``config.json``, so no override is applied here.
    Heavy imports happen here, never at module level.
    """
    if spec.name == "none":
        return None
    if spec.name == "4bit":
        import torch
        from transformers import BitsAndBytesConfig

        return BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
        )
    if spec.name == "8bit":
        from transformers import BitsAndBytesConfig

        return BitsAndBytesConfig(load_in_8bit=True)
    # gptq / awq: pre-quantized weights; rely on the model's own config.json.
    return None


def resolve_training_quant_config(spec: QuantSpec):
    """Return model kwargs for QLoRA-style training.

    Only bnb 4bit/8bit are supported for training; gptq/awq are inference-only
    artifacts produced by ``kiln quantize``.
    """
    if spec.name in ("gptq", "awq"):
        raise KilnError(
            message=f"Quantization {spec.name!r} is inference-only.",
            hint="Use none/4bit/8bit for training, or load a quantized artifact via serve.",
            exit_code=USAGE,
        )
    return resolve_load_quant_config(spec)
