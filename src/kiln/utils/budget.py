"""Torch-free analytic VRAM preflight — pure math, no CUDA import.

Estimates memory for QLoRA NF4 training.  The formula is approximate
(intentionally conservative) so it can gate decisions *before* any
heavy import.  Real allocation is verified by the trainer; this
module just refuses obviously doomed runs early.

Memory model (NF4 QLoRA), priced as additive components:

    base weights      params × 0.5          (NF4 quantized, frozen)
    + trainable       lora_params × 2.0     (LoRA adapter weights, fp16)
    + optimizer       trainable × 8.0       (AdamW fp32 m + v, trainable only)
    + activation      batch × seq × hidden × 2 × overhead
    + runtime         RUNTIME_WORKSPACE_BYTES (fixed compute/scratch buffers)
    = raw peak
    raw peak × (1 + safety_margin)

Earlier revisions priced only the base weights plus a small LoRA/activation
surcharge and never added the trainable-parameter AdamW moments, so QLoRA
estimates came in 2–3× too optimistic (e.g. 7B ≈ 3.9 GB vs the community
8–12 GB figure).  The optimizer term is charged on *trainable* (LoRA)
parameters only — never the frozen NF4 base — which is the single correction
that closes the gap without over-correcting.

All sizes in bytes.  Returns a VRAMPreflight with estimated and
available values; the caller decides whether to proceed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# Per-parameter byte costs (see memory model above).  Named constants make
# the accounting easy to revise when measured allocation justifies a change.
NF4_BYTES_PER_PARAM = 0.5
FP16_BYTES_PER_PARAM = 2.0
ADAM_MOMENT_BYTES_PER_PARAM = 8.0  # fp32 m + fp32 v, trainable params only
ACTIVATION_OVERHEAD = 4  # rough activation-checkpointing overhead multiplier
DEFAULT_SAFETY_MARGIN = 0.10

# Real runtime component that should not disappear inside the generic safety
# margin: compute/scratch/transient buffers beyond activations.  1 GiB is a
# conservative floor; revise when measurements justify it.
RUNTIME_WORKSPACE_BYTES = 1 * 1024**3


class GPUDetector(Protocol):
    """Minimal interface for querying available VRAM."""

    def total_vram_bytes(self) -> int: ...


@dataclass(frozen=True)
class VRAMPreflight:
    """Result of a VRAM estimate."""

    estimated_bytes: int
    available_bytes: int
    fits: bool
    margin_bytes: int  # available - estimated (positive = headroom)

    @property
    def estimated_gb(self) -> float:
        """Estimated VRAM usage in GB for a given config."""
        return self.estimated_bytes / (1024**3)

    @property
    def available_gb(self) -> float:
        """Available VRAM in GB across detected GPUs."""
        return self.available_bytes / (1024**3)

    @property
    def margin_gb(self) -> float:
        """Slack between available and estimated VRAM, in GB."""
        return self.margin_bytes / (1024**3)


def _lora_param_count(
    *,
    lora_rank: int,
    lora_target_modules: int,
    hidden_size: int,
) -> int:
    """Trainable LoRA parameter count.

    Each target module gets two low-rank matrices: A (hidden × rank) and
    B (rank × hidden), so 2 × rank × hidden parameters per module.
    """
    return lora_target_modules * lora_rank * hidden_size * 2


def _vram_budget(
    *,
    param_count: int,
    lora_rank: int,
    lora_target_modules: int,
    batch_size: int,
    seq_len: int,
    hidden_size: int,
    safety_margin_fraction: float = DEFAULT_SAFETY_MARGIN,
) -> dict[str, int]:
    """Model QLoRA NF4 training VRAM as additive byte components.

    Returns a dict keyed by component name, all *raw* (pre-margin) except
    ``total`` which folds in the safety margin.  Breaking the accounting
    into components keeps the estimator auditable and lets the streaming
    path stream only the layer-divisible base term.

    Component semantics (see module docstring):
      - base:       NF4 quantized *frozen* base weights (layer-divisible).
      - trainable:  LoRA adapter weights in fp16.
      - optimizer:  AdamW moments (fp32 m + v) on trainable params only.
      - activation: batch × seq × hidden × 2 × overhead.
      - runtime:    fixed compute/scratch workspace.
    """
    base_bytes = int(param_count * NF4_BYTES_PER_PARAM)
    lora_params = _lora_param_count(
        lora_rank=lora_rank,
        lora_target_modules=lora_target_modules,
        hidden_size=hidden_size,
    )
    trainable_bytes = int(lora_params * FP16_BYTES_PER_PARAM)
    optimizer_bytes = int(lora_params * ADAM_MOMENT_BYTES_PER_PARAM)
    activation_bytes = (
        batch_size * seq_len * hidden_size * 2 * ACTIVATION_OVERHEAD
    )
    runtime_bytes = RUNTIME_WORKSPACE_BYTES

    raw_peak = base_bytes + trainable_bytes + optimizer_bytes + activation_bytes + runtime_bytes
    margin = int(raw_peak * safety_margin_fraction)
    return {
        "base_bytes": base_bytes,
        "trainable_bytes": trainable_bytes,
        "optimizer_bytes": optimizer_bytes,
        "activation_bytes": activation_bytes,
        "runtime_bytes": runtime_bytes,
        "raw_peak": raw_peak,
        "margin_bytes": margin,
        "total": raw_peak + margin,
    }


def estimate_vram_bytes(
    *,
    param_count: int,
    lora_rank: int,
    lora_target_modules: int,
    batch_size: int,
    seq_len: int,
    hidden_size: int,
    safety_margin_fraction: float = 0.10,
) -> int:
    """Estimate QLoRA NF4 training VRAM in bytes (flat, full-resident peak).

    Parameters
    ----------
    param_count : int
        Total parameters in the base model.
    lora_rank : int
        LoRA r value.
    lora_target_modules : int
        Number of modules receiving LoRA adapters (approximate multiplier
        for LoRA parameter count; typically 4–8 for a 7B model).
    batch_size : int
        Training batch size.
    seq_len : int
        Max sequence length.
    hidden_size : int
        Model hidden dimension (for activation estimate).
    safety_margin_fraction : float
        Fraction added on top as safety buffer (default 10%).
    """
    return _vram_budget(
        param_count=param_count,
        lora_rank=lora_rank,
        lora_target_modules=lora_target_modules,
        batch_size=batch_size,
        seq_len=seq_len,
        hidden_size=hidden_size,
        safety_margin_fraction=safety_margin_fraction,
    )["total"]


def estimate_streaming_vram_bytes(
    *,
    param_count: int,
    lora_rank: int,
    lora_target_modules: int,
    batch_size: int,
    seq_len: int,
    hidden_size: int,
    layers: int,
    safety_margin_fraction: float = 0.10,
) -> int:
    """Streaming-aware estimate: only the base weights are layer-divisible.

    The frozen NF4 base is streamed one layer at a time (its peak residency
    drops to one layer).  Trainable LoRA + optimizer + activation + runtime
    are active/fixed per-layer costs and stay flat — the streamer keeps the
    training-state it operates on, so they must not be divided away.

    This consumes the same component model as :func:`estimate_vram_bytes`
    without changing either public contract; the existing
    :func:`kiln.trainer.layer_stream.estimate_streaming_peak` primitive is
    reused for just the base term.
    """
    from kiln.trainer.layer_stream import estimate_streaming_peak

    budget = _vram_budget(
        param_count=param_count,
        lora_rank=lora_rank,
        lora_target_modules=lora_target_modules,
        batch_size=batch_size,
        seq_len=seq_len,
        hidden_size=hidden_size,
        safety_margin_fraction=safety_margin_fraction,
    )

    # Stream only the layer-divisible base term.
    base_streamed = estimate_streaming_peak(
        full_vram_bytes=budget["base_bytes"],
        layers=layers,
        overhead_bytes=0,
    ).streaming_peak_bytes

    fixed_peak = (
        budget["trainable_bytes"]
        + budget["optimizer_bytes"]
        + budget["activation_bytes"]
        + budget["runtime_bytes"]
    )
    raw_peak = base_streamed + fixed_peak
    margin = int(raw_peak * safety_margin_fraction)
    return raw_peak + margin


def check_vram(
    *,
    param_count: int,
    lora_rank: int,
    lora_target_modules: int,
    batch_size: int,
    seq_len: int,
    hidden_size: int,
    available_vram_bytes: int,
    safety_margin_fraction: float = 0.10,
) -> VRAMPreflight:
    """Run the VRAM preflight check."""
    estimated = estimate_vram_bytes(
        param_count=param_count,
        lora_rank=lora_rank,
        lora_target_modules=lora_target_modules,
        batch_size=batch_size,
        seq_len=seq_len,
        hidden_size=hidden_size,
        safety_margin_fraction=safety_margin_fraction,
    )
    margin = available_vram_bytes - estimated
    return VRAMPreflight(
        estimated_bytes=estimated,
        available_bytes=available_vram_bytes,
        fits=margin >= 0,
        margin_bytes=margin,
    )
