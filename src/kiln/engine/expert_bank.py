"""V2 MoE expert banks — CPU↔GPU offload / hybrid placement (plan A9).

This is the pure-Python control plane for mixture-of-experts weight residency.
Real tensor movement is delegated to an injectable ``mover`` callback so the
placement policy, eviction order, and decode-only guard are fully testable
without a GPU or torch. The GPU-resident set is tracked by the LFRU tier
(plan A5) so eviction honours the same cold-LFU / hot-LRU policy as the memory
tier it sits behind.

Strategies
----------
* ``offload`` — experts live on GPU when hot, spill to CPU when evicted.
* ``hybrid``  — GPU for the hottest, CPU for warm, disk for cold (three tiers).
* ``cpu``     — everything stays on CPU (no GPU residency at all).

The decode-only expert-budget guard (plan A8) is enforced here too: an explicit
trim (eviction to free space) outside the decode phase raises ``DecodeOnlyError``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from kiln.engine.cache_tier import LFRUTier
from kiln.engine.expert_budget import DecodeOnlyError

Strategy = Enum("Strategy", "offload hybrid cpu")


@dataclass(frozen=True)
class Expert:
    """An opaque expert-weight handle.

    ``size_bytes`` is the GPU footprint; the bank never touches the bytes
    itself — movement is performed by the injected ``mover``. ``layer`` and
    ``dims`` are topology metadata used by the spec/validator (plan V3).
    """

    expert_id: str
    size_bytes: int
    layer: int = 0
    dims: int = 0


# mover(expert, from_tier, to_tier) -> None  (side effect: physically move weights)
Mover = Callable[[Expert, str, str], None]

_GPU = "gpu"
_CPU = "cpu"
_DISK = "disk"


class ExpertBank:
    """Manages MoE expert residency under a GPU memory budget.

    Parameters
    ----------
    gpu_capacity_bytes:
        Max GPU footprint for resident experts (ignored for the ``cpu`` strategy).
    strategy:
        Placement strategy (see module docstring).
    mover:
        Callback invoked whenever an expert changes tier, so the caller can
        perform the real weight transfer. Default records moves in ``moves``.
    """

    def __init__(
        self,
        gpu_capacity_bytes: int,
        strategy: Strategy = Strategy.offload,
        mover: Optional[Mover] = None,
    ) -> None:
        self._gpu_capacity = gpu_capacity_bytes
        self._strategy = strategy
        self._mover = mover or self._record_move
        self._gpu_used = 0
        # Resident-on-GPU set, ordered by LFRU policy for eviction.
        self._resident: LFRUTier[str, Expert] = LFRUTier(capacity=10_000)
        self._cpu: dict[str, Expert] = {}
        self._disk: dict[str, Expert] = {}
        # Full topology (every expert descriptor), independent of residency.
        self._all_experts: dict[str, Expert] = {}
        self.moves: list[tuple[Expert, str, str]] = []
        self._decode_phase = False

    # -- phase tracking (decode-only guard) -----------------------------------
    def enter_decode(self) -> None:
        """Mark the decode phase (expert trimming/eviction is now allowed)."""
        self._decode_phase = True

    def exit_decode(self) -> None:
        self._decode_phase = False

    # -- topology API ---------------------------------------------------------
    def register(self, expert: Expert) -> None:
        """Record an expert in the topology (CPU-side descriptor by default).

        Registration just records the descriptor so the engine knows the model's
        expert set; actual GPU residency is established on demand via
        :meth:`ensure_resident` during the decode phase.
        """
        self._all_experts[expert.expert_id] = expert
        self._cpu.setdefault(expert.expert_id, expert)

    @property
    def experts(self) -> dict[str, Expert]:
        """All registered expert descriptors (topology view)."""
        return dict(self._all_experts)

    # -- residency API --------------------------------------------------------
    def is_resident(self, expert_id: str) -> bool:
        return expert_id in self._resident

    def ensure_resident(self, expert: Expert) -> None:
        """Guarantee ``expert`` is on GPU, offloading others if needed."""
        if expert.expert_id in self._resident:
            self._resident.get(expert.expert_id)  # touch → promotion
            return
        if self._strategy == Strategy.cpu:
            # cpu strategy: never promote to GPU.
            self._cpu[expert.expert_id] = expert
            self._mover(expert, "load", _CPU)
            return
        # Evict until there is room (only during decode for trimming).
        while self._gpu_used + expert.size_bytes > self._gpu_capacity:
            if not self._evict_one():
                # Cannot make room → refuse rather than corrupt state.
                raise MemoryError(
                    f"Cannot fit expert {expert.expert_id} within GPU budget "
                    f"{self._gpu_capacity} bytes"
                )
        self._place_gpu(expert)

    def _evict_one(self) -> bool:
        if self._resident.size == 0:
            return False
        if not self._decode_phase:
            raise DecodeOnlyError(
                "expert eviction (trimming) is only permitted during the decode phase"
            )
        victim_id, victim = self._resident.evict()
        self._gpu_used -= victim.size_bytes
        target = _CPU if self._strategy == Strategy.offload else _DISK
        self._mover(victim, _GPU, target)
        if target == _CPU:
            self._cpu[victim_id] = victim
        else:
            self._disk[victim_id] = victim
        return True

    def rebalance(self, keep_fraction: float = 0.5) -> int:
        """Evict resident experts until GPU usage is ``<= gpu_capacity * keep_fraction``.

        Elastic VRAM rebalance: frees GPU headroom before a new allocation so the
        scheduler can avoid OOM instead of failing. Decode-phase only (the same
        trimming guard as colibri #292 — moving experts mid-prefill corrupts
        in-flight kernels). Returns the number of experts evicted.
        """
        if not 0.0 <= keep_fraction <= 1.0:
            raise ValueError("keep_fraction must be in [0, 1]")
        target = int(self._gpu_capacity * keep_fraction)
        evicted = 0
        while self._gpu_used > target:
            if not self._evict_one():
                break
            evicted += 1
        return evicted

    def _place_gpu(self, expert: Expert) -> None:
        came_from = (
            _CPU
            if expert.expert_id in self._cpu
            else _DISK
            if expert.expert_id in self._disk
            else "load"
        )
        if expert.expert_id in self._cpu:
            del self._cpu[expert.expert_id]
        if expert.expert_id in self._disk:
            del self._disk[expert.expert_id]
        self._resident.put(expert.expert_id, expert)
        self._gpu_used += expert.size_bytes
        self._mover(expert, came_from, _GPU)

    # -- introspection --------------------------------------------------------
    @property
    def gpu_used_bytes(self) -> int:
        return self._gpu_used

    @property
    def resident_ids(self) -> list[str]:
        return list(self._resident.keys())

    def _record_move(self, expert: Expert, _from: str, _to: str) -> None:
        self.moves.append((expert, _from, _to))
