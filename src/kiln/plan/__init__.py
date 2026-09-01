"""Plan — recommend backend and config based on hardware.

Detects GPU, RAM, and disk; recommends backend (cuda/cpu), quantization level,
VRAM/RAM budget. Optionally writes a kiln.yaml config file.

Also classifies whether a QLoRA training run *fits* on the detected hardware,
mapping an estimated VRAM peak against configurable policy thresholds into a
verdict (Recommended / Possible with constrained settings / Likely OOM /
Unsupported).  The thresholds live in the top-level ``plan:`` config block so
policy can be tuned without touching the estimator or the recipe.
"""

from __future__ import annotations

import enum
import os
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol


class Verdict(enum.Enum):
    """Feasibility verdict for a QLoRA training run on detected hardware."""

    RECOMMENDED = "Recommended"
    POSSIBLE_CONSTRAINED = "Possible (constrained settings)"
    LIKELY_OOM = "Likely OOM"
    UNSUPPORTED = "Unsupported"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


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
    training_verdict: Verdict | None = field(default=None)

    def to_dict(self) -> dict:
        """Serialize this plan result to a plain dict."""
        d = asdict(self)
        if d["training_verdict"] is not None:
            d["training_verdict"] = d["training_verdict"].value
        return d


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


class _FitPolicy(Protocol):
    """Shape of the configurable plan: thresholds (from PlanPolicyConfig)."""

    recommended_fraction: float
    possible_fraction: float
    minimum_vram_bytes: int


def classify_fit(
    *,
    estimated_bytes: int,
    available_bytes: int,
    policy: _FitPolicy,
) -> Verdict:
    """Classify whether a training run fits, from an estimate + policy.

    Uses ``available_bytes`` as the hardware ceiling and the configurable
    policy thresholds as the classification boundaries:

    - ``Unsupported`` when available is below the minimum hardware floor.
    - ``Recommended`` when estimated <= available × recommended_fraction
      (>0.10 headroom given the estimator's own margin).
    - ``Possible (constrained settings)`` when estimated <= available ×
      possible_fraction — viable only with reduced batch/seq or streaming.
    - ``Likely OOM`` otherwise.
    """
    if available_bytes <= 0:
        return Verdict.UNSUPPORTED
    if available_bytes < policy.minimum_vram_bytes:
        return Verdict.UNSUPPORTED

    if estimated_bytes <= available_bytes * policy.recommended_fraction:
        return Verdict.RECOMMENDED
    if estimated_bytes <= available_bytes * policy.possible_fraction:
        return Verdict.POSSIBLE_CONSTRAINED
    return Verdict.LIKELY_OOM


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

    # Representative QLoRA training-fit verdict for a ~7B model against the
    # detected VRAM, using default policy thresholds.  Pure torch-free math.
    training_verdict: Verdict | None = None
    if vram_gb:
        from kiln.config.schema import PlanPolicyConfig
        from kiln.utils.budget import estimate_vram_bytes

        estimated = estimate_vram_bytes(
            param_count=7_000_000_000,
            lora_rank=16,
            lora_target_modules=6,
            batch_size=4,
            seq_len=2048,
            hidden_size=4096,
        )
        policy = PlanPolicyConfig()
        training_verdict = classify_fit(
            estimated_bytes=estimated,
            available_bytes=int(vram_gb * 1024**3),
            policy=policy,
        )

    return PlanResult(
        backend=backend,
        quant_recommendation=quant,
        vram_gb=vram_gb,
        ram_gb=ram_gb,
        disk_free_gb=disk_gb,
        reasoning=reasoning,
        suggested_config=suggested,
        training_verdict=training_verdict,
    )


def format_plan(plan: PlanResult) -> str:
    """Render a PlanResult as a human-readable string."""
    lines = [
        f"Backend:     {plan.backend}",
        f"Quant:       {plan.quant_recommendation}",
    ]
    if plan.training_verdict is not None:
        lines.append(f"Train fit:   {plan.training_verdict.value}")
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
