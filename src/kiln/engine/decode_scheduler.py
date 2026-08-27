"""V2 decode scheduler — fixed-address, graph-capturable decode (plan V2 kernels).

The decode loop is the hot path of inference. To make it amenable to CUDA graph
capture (one static graph replays every step at a fixed address), the per-step
computation must be a *fixed sequence of operations* — no control flow that
changes shape between steps. This module models that contract in pure Python so
the scheduler, step accounting, and the decode-only expert-trim guard are
testable without a GPU. A real kernel backend would capture ``capture()`` with
``torch.cuda.graph``; here it is replayed as a frozen callable.
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

# A single decode step: maps a state to the next state. Must be shape-stable so
# the step sequence can be captured as one static graph.
State = object


@runtime_checkable
class DecodeStep(Protocol):
    """One fixed-address decode operation."""

    def __call__(self, state: State) -> State: ...


class DecodeScheduler:
    """Runs a fixed sequence of decode steps.

    Parameters
    ----------
    steps:
        The ordered decode-step callables. This sequence is the "graph": it must
        be identical on every decode iteration for capture to be valid.
    max_steps:
        Safety cap on decode iterations.
    """

    def __init__(self, steps: list[DecodeStep], max_steps: int = 4096) -> None:
        self._steps = list(steps)
        self._max_steps = max_steps
        self._step_count = 0
        self._captured: Callable[[State], State] | None = None

    @property
    def step_count(self) -> int:
        """Total decode steps executed across all runs."""
        return self._step_count

    @property
    def captured(self) -> bool:
        """Whether a static graph has been captured."""
        return self._captured is not None

    def run(self, initial: State, n_steps: int) -> State:
        """Run ``n_steps`` decode iterations from ``initial`` state."""
        if n_steps > self._max_steps:
            raise ValueError(f"n_steps {n_steps} exceeds max_steps {self._max_steps}")
        state = initial
        for _ in range(n_steps):
            for step in self._steps:
                state = step(state)
            self._step_count += 1
        return state

    def capture(self) -> Callable[[State], State]:
        """Freeze the step sequence into a single replayable callable.

        Real backends would wrap this in ``torch.cuda.graph``; here we close over
        the step list. The returned callable applies one full decode iteration.
        """
        steps = list(self._steps)

        def _replay(state: State) -> State:
            for step in steps:
                state = step(state)
            return state

        self._captured = _replay
        return _replay

    def run_captured(self, initial: State, n_steps: int) -> State:
        """Run with the captured graph (must call :meth:`capture` first)."""
        if self._captured is None:
            raise RuntimeError("call capture() before run_captured()")
        if n_steps > self._max_steps:
            raise ValueError(f"n_steps {n_steps} exceeds max_steps {self._max_steps}")
        state = initial
        for _ in range(n_steps):
            state = self._captured(state)
            self._step_count += 1
        return state
