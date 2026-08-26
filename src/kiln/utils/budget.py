"""Torch-free analytic VRAM preflight — pure math, no CUDA import.

Estimates memory for QLoRA NF4 training.  The formula is approximate
(intentionally conservative) so it can gate decisions *before* any
heavy import.  Real allocation is verified by the trainer; this
module just refuses obviously doomed runs early.

Memory model (NF4 QLoRA):
  base_params × 0.5 bytes  (NF4 quantized weights)
  + grad (base_params × 2 bytes, fp16)
  + optimizer states (base_params × 8 bytes, AdamW fp32 m+v)
  + LoRA params + grads + states (lora_params × ...)
  + activation memory (batch × seq_len × hidden × overhead)
  + 10% safety margin

All sizes in bytes.  Returns a VRAMPreflight with estimated and
available values; the caller decides whether to proceed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


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
        return self.estimated_bytes / (1024**3)

    @property
    def available_gb(self) -> float:
        return self.available_bytes / (1024**3)

    @property
    def margin_gb(self) -> float:
        return self.margin_bytes / (1024**3)


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
    """Estimate QLoRA NF4 training VRAM in bytes.

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
    # Base model: NF4 quantized weights
    base_bytes = param_count // 2  # 0.5 bytes per param (NF4)

    # LoRA: rank × 2 matrices per target module
    # Each module: A (hidden × rank) + B (rank × hidden) params
    lora_hidden = hidden_size
    lora_params = lora_target_modules * lora_rank * lora_hidden * 2
    # LoRA: weights + grads + optimizer = ~10 bytes per param (fp16 + fp32×2)
    lora_bytes = lora_params * 10

    # Activation memory: batch * seq_len * hidden * 2 (fp16) * overhead
    activation_overhead = 4  # rough activation checkpointing overhead
    activation_bytes = batch_size * seq_len * hidden_size * 2 * activation_overhead

    raw = base_bytes + lora_bytes + activation_bytes
    margin = int(raw * safety_margin_fraction)
    return raw + margin


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
