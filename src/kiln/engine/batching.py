"""V2 continuous batching scheduler (plan V2 continuous batching).

In-flight requests enter a queue; the scheduler groups them into batches up to a
max size, releasing finished requests and admitting new ones as capacity frees.
Pure-Python and deterministic so the admission order is unit-testable without a
GPU.
"""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


class ContinuousBatcher:
    """Admits requests into batches of at most ``max_batch`` in arrival order."""

    def __init__(self, max_batch: int = 8) -> None:
        if max_batch < 1:
            raise ValueError("max_batch must be >= 1")
        self.max_batch = max_batch
        self._waiting: list[T] = []
        self._active: list[T] = []

    def submit(self, request: T) -> None:
        self._waiting.append(request)

    def step(self) -> list[T]:
        """Form the next batch from the waiting queue, up to max_batch.

        Returns the current active batch (resets each call; a real engine would
        run the returned batch and then call ``complete`` per item).
        """
        room = self.max_batch - len(self._active)
        if room > 0:
            admitted = self._waiting[:room]
            self._waiting = self._waiting[room:]
            self._active.extend(admitted)
        return list(self._active)

    def complete(self, request: T) -> None:
        if request in self._active:
            self._active.remove(request)

    @property
    def pending(self) -> int:
        return len(self._waiting) + len(self._active)
