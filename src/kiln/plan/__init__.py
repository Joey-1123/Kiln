"""Plan — recommend backend and config based on hardware.

Detects GPU, RAM, and disk; recommends backend (cuda/cpu), quantization level,
VRAM/RAM budget. Optionally writes a kiln.yaml config file.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PlanResult:
    """Hardware recommendation result (backend, quant, specs)."""
    backend: str
    quant_recommendation: str
    vram_gb: float | None
    ram_gb: float | None
    disk_free_gb: float | None
    reasoning: str
    suggested_config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize this plan result to a plain dict."""
        return asdict(self)


def _get_gpu_info() -> tuple[str | None, float | None]:
    """Returns (gpu_name, vram_gb) or (None, None)."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            line = result.stdout.strip().split("\n")[0]
            parts = line.split(",")
            name = parts[0].strip()
            vram = float(parts[-1].strip()) / 1024
            return name, vram
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    return None, None


def _get_ram_gb() -> float | None:
    try:
        import psutil
        return psutil.virtual_memory().total / (1024 ** 3)
    except ImportError:
        return None


def _get_disk_free_gb() -> float | None:
    try:
        usage = os.statvfs("/")
        return (usage.f_bavail * usage.f_frsize) / (1024 ** 3)
    except OSError:
        return None


def build_plan() -> PlanResult:
    """Detect hardware and recommend a serving configuration."""
    gpu_name, vram_gb = _get_gpu_info()
    ram_gb = _get_ram_gb()
    disk_gb = _get_disk_free_gb()

    backend = "cuda" if gpu_name and vram_gb and vram_gb >= 4.0 else "cpu"

    if backend == "cuda":
        if vram_gb and vram_gb >= 12.0:
            quant = "Q5_K_M"
            reasoning = (
                f"GPU {gpu_name} with {vram_gb:.1f} GB VRAM — "
                "can run quantized 7-14B models comfortably."
            )
        elif vram_gb and vram_gb >= 8.0:
            quant = "Q4_K_M"
            reasoning = (
                f"GPU {gpu_name} with {vram_gb:.1f} GB VRAM — "
                "Q4_K_M recommended for 7B models."
            )
        else:
            quant = "Q4_K_M"
            reasoning = (
                f"GPU {gpu_name} with {vram_gb:.1f} GB VRAM — "
                "limited; small models only, Q4_K_M required."
            )
    else:
        quant = "Q8_0"
        reasoning = (
            "No CUDA GPU detected. CPU serving available via llama.cpp backend."
            + (f" {ram_gb:.1f} GB RAM." if ram_gb else "")
        )

    suggested: dict[str, Any] = {
        "serving": {
            "backend": backend,
            "quantization": quant,
        },
    }

    return PlanResult(
        backend=backend,
        quant_recommendation=quant,
        vram_gb=vram_gb,
        ram_gb=ram_gb,
        disk_free_gb=disk_gb,
        reasoning=reasoning,
        suggested_config=suggested,
    )


def format_plan(plan: PlanResult) -> str:
    """Render a PlanResult as a human-readable string."""
    lines = [
        f"Backend:     {plan.backend}",
        f"Quant:       {plan.quant_recommendation}",
    ]
    if plan.vram_gb is not None:
        lines.append(f"VRAM:        {plan.vram_gb:.1f} GB")
    else:
        lines.append("VRAM:        N/A")
    if plan.ram_gb is not None:
        lines.append(f"RAM:         {plan.ram_gb:.1f} GB")
    else:
        lines.append("RAM:         N/A")
    if plan.disk_free_gb is not None:
        lines.append(f"Disk free:   {plan.disk_free_gb:.1f} GB")
    lines.append(f"\nReasoning:   {plan.reasoning}")
    return "\n".join(lines)
