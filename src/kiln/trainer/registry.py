"""V2 adapter registry with lineage (plan V2 adapter registry).

Fine-tunes produce adapters. The registry records each adapter's base model and
its parent adapter, so a lineage chain can be reconstructed (A was tuned from base
B, which was tuned from base C). Pure data + lookups; persistence is injectable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class AdapterRecord:
    name: str
    base_model: str
    parent: str | None
    created_at: float


class AdapterRegistry:
    """In-memory adapter registry with lineage resolution."""

    def __init__(self, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._adapters: dict[str, AdapterRecord] = {}

    def register(
        self, name: str, base_model: str, parent: str | None = None
    ) -> AdapterRecord:
        if parent is not None and parent not in self._adapters:
            raise KeyError(f"parent adapter {parent!r} not registered")
        rec = AdapterRecord(
            name=name, base_model=base_model, parent=parent, created_at=self._now()
        )
        self._adapters[name] = rec
        return rec

    def get(self, name: str) -> AdapterRecord:
        return self._adapters[name]

    def list(self) -> list[AdapterRecord]:
        return list(self._adapters.values())

    def lineage(self, name: str) -> list[AdapterRecord]:
        """Return the adapter chain from this adapter back to its root."""
        chain: list[AdapterRecord] = []
        current: str | None = name
        seen: set[str] = set()
        while current is not None:
            if current in seen:
                raise ValueError(f"lineage cycle at {current!r}")
            seen.add(current)
            rec = self._adapters[current]
            chain.append(rec)
            current = rec.parent
        return chain
