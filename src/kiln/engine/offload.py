"""V2-3 offload coordinator — CPU↔GPU banks behind one seam.

Wires ``ExpertBank`` + ``LFRUTier`` + ``MoESpec`` + ``ExpertBudget`` into a
single coordinator the Engine can own. All movement is delegated to an
injectable mover so the control plane is pure-Python and testable without
torch or CUDA; the real weight transfer is the backend's job behind the same
interface.

The coordinator is strategy-aware (offload/hybrid/cpu) and enforces the
decode-only expert-budget guard end-to-end (prefill corruption is the
canonical V2 landmine).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from kiln.engine.cache_tier import LFRUTier
from kiln.engine.expert_bank import Expert, ExpertBank, Strategy
from kiln.engine.expert_budget import DecodeOnlyError, ExpertBudget
from kiln.engine.moe_spec import MoESpec, build_expert_bank, validate_moe_spec


@dataclass(frozen=True)
class OffloadStats:
    gpu_used_bytes: int
    gpu_capacity_bytes: int
    resident_experts: int
    registered_experts: int
    phase: str


class OffloadCoordinator:
    """Coordinates expert residency under a GPU budget.

    Parameters
    ----------
    spec:
        Validated MoE topology.
    gpu_capacity_bytes:
        GPU budget for expert weights.
    strategy:
        Placement strategy (offload/hybrid/cpu).
    mover:
        Optional weight-movement callback forwarded to ``ExpertBank``.
    tier_capacity:
        LFRU capacity for prefix/KV hot-cache (independent of expert bank).
    """

    def __init__(
        self,
        spec: MoESpec,
        gpu_capacity_bytes: int = 8 << 30,
        strategy: Strategy = Strategy.offload,
        mover: Callable[[Expert, str, str], None] | None = None,
        tier_capacity: int = 512,
    ) -> None:
        validate_moe_spec(spec)
        self._spec = spec
        self._bank: ExpertBank = build_expert_bank(
            spec,
            strategy=strategy.name,
            gpu_capacity_bytes=gpu_capacity_bytes,
            mover=mover,
        )
        self._strategy = strategy
        self._gpu_capacity = gpu_capacity_bytes
        self._budget = ExpertBudget(total_experts=spec.num_experts * spec.layers)
        self._tier: LFRUTier[str, str] = LFRUTier(capacity=tier_capacity)
        self._phase = "idle"

    @property
    def spec(self) -> MoESpec:
        return self._spec

    @property
    def strategy(self) -> Strategy:
        return self._strategy

    @property
    def phase(self) -> str:
        return self._phase

    def begin_prefill(self) -> None:
        self._phase = "prefill"
        self._budget.begin_prefill()
        self._bank.exit_decode()

    def begin_decode(self) -> None:
        self._phase = "decode"
        self._budget.begin_decode()
        self._bank.enter_decode()

    def end_phase(self) -> None:
        self._phase = "idle"
        self._budget.end()
        self._bank.exit_decode()

    def ensure_experts(self, expert_ids: list[str]) -> None:
        """Ensure the listed experts are resident for the current decode step."""
        if self._phase != "decode" and any(not self._bank.is_resident(eid) for eid in expert_ids):
            raise DecodeOnlyError("expert residency change outside decode phase")
        for eid in expert_ids:
            exp = self._bank.experts.get(eid)
            if exp is None:
                raise KeyError(f"unknown expert {eid!r}")
            self._bank.ensure_resident(exp)
            self._tier.put(eid, eid)

    def trim_experts(self, expert_ids: list[int]) -> None:
        """Decode-only trim via ExpertBudget."""
        self._budget.trim(expert_ids)

    def rebalance(self, keep_fraction: float = 0.5) -> int:
        """Elastic VRAM rebalance: free GPU headroom across experts and prefix cache.

        Delegates to the expert bank (evicts resident expert weights back to CPU
        until ``gpu_used <= capacity * keep_fraction``) and the LFRU prefix tier.
        Expert eviction is decode-phase only (colibri #292 guard); the tier is
        trimmed regardless. Returns total entries evicted.
        """
        if not 0.0 <= keep_fraction <= 1.0:
            raise ValueError("keep_fraction must be in [0, 1]")
        expert_evictions = self._bank.rebalance(keep_fraction=keep_fraction)
        tier_evictions = self._tier.rebalance(keep_fraction=keep_fraction)
        return expert_evictions + tier_evictions

    def stats(self) -> OffloadStats:
        return OffloadStats(
            gpu_used_bytes=self._bank.gpu_used_bytes,
            gpu_capacity_bytes=self._gpu_capacity,
            resident_experts=len(self._bank.resident_ids),
            registered_experts=len(self._bank.experts),
            phase=self._phase,
        )

    @property
    def bank(self) -> ExpertBank:
        return self._bank

    @property
    def tier(self) -> LFRUTier[str, str]:
        return self._tier

    @property
    def budget(self) -> ExpertBudget:
        return self._budget
