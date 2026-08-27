"""Bandwidth measurement for V2 self-calibration (plan A10).

Lazy-imports torch only when actually measuring, so the module stays usable
in the torch-free zone. Returns ``None`` when CUDA/torch is unavailable —
callers then fall back to the cached value or a conservative default.
"""

from __future__ import annotations

from typing import Optional


def measure_bandwidth_gbps() -> Optional[float]:
    """Estimate memory bandwidth (GB/s) via a CUDA matmul.

    Returns ``None`` when torch or CUDA is unavailable. Sized to exceed the
    GPU cache so the result reflects DRAM↔compute bandwidth, not SRAM.
    """
    try:
        import torch
    except ImportError:
        return None
    if not torch.cuda.is_available():
        return None

    import time

    dev = torch.device("cuda")
    n = 8192
    a = torch.randn(n, n, device=dev, dtype=torch.float32)
    b = torch.randn(n, n, device=dev, dtype=torch.float32)
    torch.cuda.synchronize()
    for _ in range(5):  # warmup
        _ = a @ b
    torch.cuda.synchronize()

    reps = 20
    start = time.perf_counter()
    for _ in range(reps):
        _ = a @ b
    torch.cuda.synchronize()
    dt = time.perf_counter() - start

    # read a + b, write c, per matmul, times (reps + warmup)
    bytes_moved = 2 * (n * n * 4) * (reps + 5)
    return bytes_moved / dt / 1e9


def recommend(bandwidth_gbps: Optional[float]) -> str:
    """Map a bandwidth measurement to a backend strategy.

    * ``cuda-native`` — fast GPUs, run the native torch backend.
    * ``hybrid-offload`` — mid-tier, offload layers to CPU/disk.
    * ``cpu`` — no usable measurement; default to the GGUF/CPU path.
    """
    if bandwidth_gbps is None:
        return "cpu"
    if bandwidth_gbps >= 400.0:
        return "cuda-native"
    if bandwidth_gbps >= 50.0:
        return "hybrid-offload"
    return "cpu"
