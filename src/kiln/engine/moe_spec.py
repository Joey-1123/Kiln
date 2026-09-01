"""V3 big-MoE native support — spec + validator (plan V3).

A MoE model spec describes the expert topology. :func:`validate_moe_spec` checks
the spec is coherent; :func:`build_expert_bank` turns a valid spec into the
:class:`~kiln.engine.expert_bank.ExpertBank` the engine routes experts through.
Loading the actual expert weights onto the GPU is the backend's job (run in CI on
real hardware); this module is pure-Python and unit-tested without a GPU.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Optional

Routing = Literal["topk", "switch"]


@dataclass(frozen=True)
class MoESpec:
    num_experts: int
    expert_dim: int
    routing: Routing = "topk"
    top_k: int = 2
    layers: int = 1

    def validate(self) -> None:
        if self.num_experts < 1:
            raise ValueError(f"num_experts must be >= 1, got {self.num_experts}")
        if self.expert_dim < 1:
            raise ValueError(f"expert_dim must be >= 1, got {self.expert_dim}")
        if self.layers < 1:
            raise ValueError(f"layers must be >= 1, got {self.layers}")
        if self.routing == "topk" and not (1 <= self.top_k <= self.num_experts):
            raise ValueError(
                f"top_k must be in [1, {self.num_experts}], got {self.top_k}"
            )


def validate_moe_spec(spec: MoESpec) -> None:
    """Raise ValueError if the spec is incoherent."""
    spec.validate()


def build_expert_bank(
    spec: MoESpec,
    strategy: str = "offload",
    gpu_capacity_bytes: int = 8 << 30,
    mover: Optional[Callable] = None,
):
    """Build an :class:`ExpertBank` with one registered expert per (layer, expert)."""
    from kiln.engine.expert_bank import Expert, ExpertBank, Strategy

    validate_moe_spec(spec)
    bank = ExpertBank(
        gpu_capacity_bytes=gpu_capacity_bytes,
        strategy=Strategy[strategy],
        mover=mover,
    )
    for layer in range(spec.layers):
        for eid in range(spec.num_experts):
            bank.register(
                Expert(
                    expert_id=f"l{layer}.e{eid}",
                    size_bytes=spec.expert_dim * 2,
                    layer=layer,
                    dims=spec.expert_dim,
                )
            )
    return bank
