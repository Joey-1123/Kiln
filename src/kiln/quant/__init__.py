"""V2 quantization menu (GPTQ / AWQ / 4bit / 8bit / none) as a capability registry.

A menu of quant schemes, each tagged with the backend that can actually run it.
The `kiln plan`/serve path consults this to offer the user a valid choice per
detected hardware, and `training.quantization` is validated against these names.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuantScheme:
    name: str
    bits: int
    backend: str  # "cuda" (GPU) or "cpu" (GGUF/llama.cpp)


SCHEMES: dict[str, QuantScheme] = {
    "none": QuantScheme("none", 16, "cuda"),
    "8bit": QuantScheme("8bit", 8, "cuda"),
    "4bit": QuantScheme("4bit", 4, "cuda"),
    "gptq": QuantScheme("gptq", 4, "cuda"),
    "awq": QuantScheme("awq", 4, "cpu"),
}

# Names accepted by `training.quantization` in the config schema.
VALID_NAMES = frozenset(SCHEMES)


def available(backend: str) -> list[str]:
    """Return scheme names usable on the given backend (plus the always-valid 'none')."""
    return sorted(n for n, s in SCHEMES.items() if s.backend == backend or n == "none")


def get(name: str) -> QuantScheme:
    return SCHEMES[name]
