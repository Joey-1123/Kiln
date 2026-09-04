"""Backend capability matrix and registry.

BackendInfo is a pure-flag dataclass — registration never imports
kernels.  The gateway queries the matrix to decide which backend
handles a request; the engine loop loads the actual backend lazily.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BackendInfo:
    """Declarative capability flags for a backend.

    None of these fields trigger an import — they are static metadata
    set at registration time.
    """

    name: str  # "cuda" | "cpu" | "roc"
    device_family: str = "any"  # "nvidia" | "amd" | "any" (accelerator it targets)
    supports_gpu: bool = False
    supports_cpu: bool = True
    supports_streaming: bool = True
    supports_tools: bool = True
    supports_nf4: bool = False
    supports_gptq: bool = False
    supports_gguf: bool = False
    supports_continuous_batching: bool = False
    supports_grammar: bool = False
    supports_cuda_graph: bool = False
    supports_triton: bool = False
    supports_offload: bool = False
    requires_cuda: bool = False
    requires_torch: bool = False
    max_model_params: int = 0  # 0 = unlimited
    description: str = ""


# ---------------------------------------------------------------------------
# Registry — populated at import time, never imports heavy deps

_REGISTRY: dict[str, BackendInfo] = {}


def register_backend(info: BackendInfo) -> None:
    """Register a backend by name.  Idempotent (last write wins)."""
    _REGISTRY[info.name] = info


def get_backend(name: str) -> BackendInfo | None:
    """Look up a backend by name."""
    return _REGISTRY.get(name)


def list_backends() -> list[BackendInfo]:
    """Return all registered backends."""
    return list(_REGISTRY.values())


def select_backend(
    *,
    prefer: str = "",
    require_gpu: bool = False,
    require_accel: str = "",  # "nvidia" | "amd" | "" (any)
    require_nf4: bool = False,
    require_gptq: bool = False,
    require_gguf: bool = False,
) -> BackendInfo | None:
    """Select the best backend matching constraints.

    Priority: explicit ``prefer`` > GPU-capable > first registered.
    ``require_accel`` (``"nvidia"``/``"amd"``) narrows to a device family, so a
    caller on AMD hardware can avoid NVIDIA-only backends. Returns None if no
    backend matches.
    """
    if prefer:
        b = get_backend(prefer)
        if b is not None and _family_ok(b, require_accel):
            return b

    candidates = list(_REGISTRY.values())
    candidates = [b for b in candidates if _family_ok(b, require_accel)]

    if require_gpu:
        candidates = [b for b in candidates if b.supports_gpu]
    if require_nf4:
        candidates = [b for b in candidates if b.supports_nf4]
    if require_gptq:
        candidates = [b for b in candidates if b.supports_gptq]
    if require_gguf:
        candidates = [b for b in candidates if b.supports_gguf]

    if not candidates:
        return None

    # Prefer GPU-capable backends
    gpu = [b for b in candidates if b.supports_gpu]
    return gpu[0] if gpu else candidates[0]


def _family_ok(info: BackendInfo, require_accel: str) -> bool:
    """True when ``info`` is acceptable for the requested accelerator."""
    if not require_accel:
        return True
    return info.device_family in ("any", require_accel)


def clear_registry() -> None:
    """Reset the registry (for testing)."""
    _REGISTRY.clear()
