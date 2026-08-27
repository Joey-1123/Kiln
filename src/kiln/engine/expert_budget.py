"""V2 expert-budget guard (plan A8).

Prior engine designs quarantined expert-budget trimming because trimming
during *prefill* corrupted attention. Kiln adopts the lesson up front:
expert-budget trimming is **decode-only**. This primitive enforces that
contract at runtime so future MoE/weight-bank code cannot regress into
prefill-time trimming.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


class DecodeOnlyError(RuntimeError):
    """Raised when expert-budget trimming is attempted outside the decode phase."""


@dataclass
class ExpertBudget:
    """Tracks active experts and enforces decode-only trimming."""

    total_experts: int
    _active: set[int] = field(default_factory=set)
    _phase: str = field(default="idle")  # idle | prefill | decode
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if self.total_experts < 1:
            raise ValueError(f"total_experts must be >= 1, got {self.total_experts}")
        self._active = set(range(self.total_experts))

    # -- phase control -----------------------------------------------------

    def begin_prefill(self) -> None:
        with self._lock:
            self._phase = "prefill"

    def begin_decode(self) -> None:
        with self._lock:
            self._phase = "decode"

    def end(self) -> None:
        with self._lock:
            self._phase = "idle"

    @property
    def phase(self) -> str:
        with self._lock:
            return self._phase

    @property
    def active(self) -> set[int]:
        with self._lock:
            return set(self._active)

    # -- budget operations --------------------------------------------------

    def trim(self, experts: list[int]) -> None:
        """Drop experts from the active set. Decode phase only."""
        with self._lock:
            if self._phase != "decode":
                raise DecodeOnlyError(
                    f"expert-budget trimming is decode-only; current phase={self._phase}"
                )
            for e in experts:
                self._active.discard(e)
