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
    backend: str  # "cuda" (NVIDIA/AMD GPU kernels) or "cpu" (GGUF/llama.cpp)


SCHEMES: dict[str, QuantScheme] = {
    "none": QuantScheme("none", 16, "cuda"),
    "8bit": QuantScheme("8bit", 8, "cuda"),
    "4bit": QuantScheme("4bit", 4, "cuda"),
    "gptq": QuantScheme("gptq", 4, "cuda"),
    "awq": QuantScheme("awq", 4, "cpu"),
}

# Names accepted by `training.quantization` in the config schema.
VALID_NAMES = frozenset(SCHEMES)

# Schemes that produce a persistent artifact via `kiln quantize`
# (gptq/awq), distinct from load/train-time schemes (none/4bit/8bit).
QUANTIZE_SCHEMES = frozenset({"gptq", "awq"})


def available(backend: str) -> list[str]:
    """Return scheme names usable on the given backend (plus the always-valid 'none').

    Both ``cuda`` and its AMD alias ``roc`` expose the same device-agnostic
    kernels, so the GPU schemes (tagged ``cuda``) are offered for either tag.
    """
    if backend == "cpu":
        return sorted(n for n, s in SCHEMES.items() if s.backend == "cpu" or n == "none")
    return sorted(n for n, s in SCHEMES.items() if s.backend == "cuda" or n == "none")


def get(name: str) -> QuantScheme:
    return SCHEMES[name]


def validate_artifact(model_dir: str, scheme: str) -> None:
    """Validate that *model_dir* is a usable quantized artifact for *scheme*.

    Raises KilnError (USAGE) if the directory is missing or lacks the
    expected quantization_config.  This is a lightweight, torch-free
    gate used by ``kiln serve`` and the CUDA load path so a produced
    artifact is never silently accepted as a plain HF dir.
    """
    import json
    from pathlib import Path

    from kiln.utils.errors import KilnError
    from kiln.utils.exitcodes import USAGE

    p = Path(model_dir)
    if not p.is_dir():
        raise KilnError(message=f"Artifact directory not found: {model_dir}", exit_code=USAGE)
    cfg_path = p / "config.json"
    if not cfg_path.is_file():
        raise KilnError(message=f"Artifact {model_dir!r} missing config.json", exit_code=USAGE)
    if scheme in QUANTIZE_SCHEMES:
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise KilnError(message=f"Cannot read {cfg_path}: {exc}", exit_code=USAGE) from exc
        has_qcfg = bool(cfg.get("quantization_config") or cfg.get("quant_config"))
        if not has_qcfg and scheme == "gptq":
            raise KilnError(
                message=f"GPTQ artifact at {model_dir!r} lacks quantization_config in config.json",
                hint="Was the artifact produced by kiln quantize --scheme gptq?",
                exit_code=USAGE,
            )
