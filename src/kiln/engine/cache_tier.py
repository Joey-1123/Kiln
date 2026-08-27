"""V2 memory tier — LFRU cache (plan A5).

Least-Frequently-Recent-Used: items live in a *cold* band (evicted by lowest
access frequency, FIFO on ties) until they cross ``promotion_threshold``
accesses, then move to a *hot* band (evicted LRU). This is the cache tier
Kiln's future expert/weight banks will sit behind; shipped now as a
dependency-free, fully-tested primitive so later engine work can adopt it
incrementally (predictive prefetch stays deferred per the plan).
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Optional

from kiln.engine.route_trace import RouteTrace, get_default

T = object  # values are opaque to the tier; kept generic-friendly via object


class LFRUTier:
    """Capacity-bounded LFRU cache split into cold (LFU) and hot (LRU) bands."""

    def __init__(
        self,
        capacity: int,
        promotion_threshold: int = 2,
        trace: Optional[RouteTrace] = None,
    ) -> None:
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity}")
        if promotion_threshold < 1:
            raise ValueError(f"promotion_threshold must be >= 1, got {promotion_threshold}")
        self._capacity = capacity
        self._promotion_threshold = promotion_threshold
        self._trace = trace or get_default()
        self._hot: "OrderedDict[str, T]" = OrderedDict()
        self._cold: "OrderedDict[str, int]" = OrderedDict()  # key -> access frequency
        self._values: dict[str, T] = {}

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def size(self) -> int:
        return len(self._hot) + len(self._cold)

    def get(self, key: str) -> T | None:
        """Return the value for ``key`` and record an access (promoting if hot)."""
        if key in self._hot:
            self._hot.move_to_end(key)
            return self._values[key]
        if key in self._cold:
            self._cold[key] += 1
            if self._cold[key] >= self._promotion_threshold:
                self._promote(key)
            return self._values[key]
        return None

    def put(self, key: str, value: T) -> None:
        """Insert or update ``key``; evicts if over capacity."""
        if key in self._hot or key in self._cold:
            self._values[key] = value
            self.get(key)  # count as an access
            return
        self._values[key] = value
        self._cold[key] = 1
        self._evict_if_needed()

    def mark_access(self, key: str) -> bool:
        """Record an access without fetching the value. Returns True if known."""
        if key in self._hot:
            self._hot.move_to_end(key)
            return True
        if key in self._cold:
            self._cold[key] += 1
            if self._cold[key] >= self._promotion_threshold:
                self._promote(key)
            return True
        return False

    def __contains__(self, key: str) -> bool:
        return key in self._hot or key in self._cold

    def keys(self) -> list[str]:
        return list(self._hot.keys()) + list(self._cold.keys())

    def clear(self) -> None:
        self._hot.clear()
        self._cold.clear()
        self._values.clear()

    def _promote(self, key: str) -> None:
        self._cold.pop(key)
        self._hot[key] = self._values[key]
        self._hot.move_to_end(key)
        self._trace.record("lfru_promote", key=key)

    def evict(self) -> tuple[str, T] | None:
        """Evict the next victim (cold-LFU then hot-LRU). Returns (key, value)."""
        return self._evict_one()

    def _evict_if_needed(self) -> None:
        while self.size > self._capacity:
            self._evict_one()

    def _evict_one(self) -> tuple[str, T] | None:
        """Evict one entry: lowest-frequency cold first, else LRU hot."""
        if self._cold:
            # min respects OrderedDict insertion order for frequency ties (FIFO).
            victim = min(self._cold.items(), key=lambda kv: kv[1])[0]
            value = self._values.pop(victim, None)
            self._cold.pop(victim)
            self._trace.record("lfru_evict", key=victim, band="cold")
            return victim, value
        if self._hot:
            victim = next(iter(self._hot))  # oldest
            value = self._values.pop(victim, None)
            self._hot.pop(victim)
            self._trace.record("lfru_evict", key=victim, band="hot")
            return victim, value
        return None
