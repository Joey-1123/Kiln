"""CUDA graph-capturable decode (plan V2 kernels, CUDA only).

The decode loop is the hot path of inference. To replay it as one static CUDA graph
every step, the per-step computation must be a *fixed sequence of operations* (no
shape-changing control flow between steps). :class:`DecodeScheduler` already models
that contract in pure Python; this module is the torch/CUDA realization:

* a decode step is a callable ``Tensor -> Tensor`` on a single resident state tensor,
* :meth:`CudaGraphDecode.capture` records one full decode iteration into a
  ``torch.cuda.Graph`` (the static state tensor is owned by the graph),
* :meth:`CudaGraphDecode.run_captured` copies new input into the static tensor,
  replays the graph, and returns the (cloned) output.

ROCm/AMD support is deferred; this targets CUDA. Imports of ``torch`` are lazy so the
module is safe to import where torch/CUDA is absent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Protocol, Sequence

if TYPE_CHECKING:  # keep torch out of the runtime import path
    from torch import Tensor
    from torch.cuda import CUDAGraph


class TorchDecodeStep(Protocol):
    """One fixed-address decode operation on a torch state tensor."""

    def __call__(self, state: Tensor) -> Tensor: ...


def _torch():
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - exercised only without torch
        raise RuntimeError(
            "torch is required for CUDA decode kernels; install the 'train' extra"
        ) from exc
    return torch


class CudaGraphDecode:
    """Runs a fixed sequence of torch decode steps, capturable as a CUDA graph."""

    def __init__(self, steps: Sequence[TorchDecodeStep]) -> None:
        self._steps = list(steps)
        self._graph = None
        self._static_state = None
        self._captured_out = None

    # -- introspection --------------------------------------------------------
    @property
    def captured(self) -> bool:
        return self._graph is not None

    @property
    def num_steps(self) -> int:
        return len(self._steps)

    # -- eager reference ------------------------------------------------------
    def run_eager(self, state: Tensor, n_iterations: int = 1) -> Tensor:
        """Run the step sequence eagerly (reference for parity vs the captured graph)."""
        out = state
        for _ in range(n_iterations):
            for step in self._steps:
                out = step(out)
        return out

    # -- graph capture / replay ----------------------------------------------
    def capture(self, seed_state: Tensor) -> CUDAGraph:
        """Record one decode iteration into a static CUDA graph.

        ``seed_state`` provides the shape/dtype of the resident state; a static copy
        is owned by the graph and reused on every replay.
        """
        torch = _torch()
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required to capture a decode graph")
        graph = torch.cuda.CUDAGraph()
        static = seed_state.detach().clone().to(torch.cuda.current_device())
        with torch.cuda.graph(graph):
            out = self.run_eager(static)
        self._graph = graph
        self._static_state = static
        self._captured_out = out
        return graph

    def run_captured(self, state: Tensor) -> Tensor:
        """Replay the captured graph with ``state`` as input; returns a cloned output."""
        if self._graph is None:
            raise RuntimeError("call capture() before run_captured()")
        self._static_state.copy_(state)
        self._graph.replay()
        return self._captured_out.detach().clone()


def make_demo_steps(dim: int, device: str = "cuda") -> list[Callable[[Tensor], Tensor]]:
    """Build a representative fixed step sequence (two linear + GELU layers).

    Used by tests and as a template for real decode steps. The sequence is fixed
    and shape-stable, satisfying the capture contract.
    """
    _torch()  # ensure torch is importable before we touch nn
    import torch.nn as nn
    import torch.nn.functional as functional

    layers = nn.Sequential(
        nn.Linear(dim, dim),
        nn.GELU(),
        nn.Linear(dim, dim),
        nn.GELU(),
    ).to(device)
    # nn.Sequential is itself a Tensor->Tensor callable, but we expose the individual
    # steps so the fixed-sequence contract is explicit.
    return [
        lambda x, _l0=layers[0]: _l0(x),
        lambda x, _a=functional.gelu: _a(x),
        lambda x, _l1=layers[2]: _l1(x),
        lambda x, _a=functional.gelu: _a(x),
    ]
