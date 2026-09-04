"""Torch-backed expert mover (plan V3 / B6).

The real weight-movement side of the :class:`~kiln.engine.expert_bank.ExpertBank`
mover seam. The bank decides *which* expert should be resident under a GPU
budget; this mover decides *how* its tensors physically travel between
``gpu`` / ``cpu`` / ``disk``.

Tensor handling
---------------
Each expert owns one or more safetensors tensors (the map produced by
:class:`~kiln.engine.safetensors_store.SafetensorsExpertStore.expert_blobs`).
The mover lazily loads those tensors as numpy (via ``safe_open(framework="numpy")``,
torch-free for read), and only converts to torch when a tensor must land on GPU.
A per-expert registry tracks the live tensors so moves are idempotent and cheap:
moving gpu->cpu keeps the (already materialized) array in memory, and moving a
tier to disk drops the reference so the bytes become eligible for reclamation.

The GPU path (``to_gpu``) lazy-imports torch and calls ``tensor.to(device)``; it
is exercised only on a CUDA box / the gpu CI job. Everything else — discovery,
size bookkeeping, cpu<->disk moves, load-from-shard — is CPU-testable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kiln.engine.expert_bank import Expert

_G_TIER = "gpu"
_C_TIER = "cpu"
_D_TIER = "disk"


class TorchExpertMover:
    """Moves an expert's tensors between tiers backed by real safetensors.

    Parameters
    ----------
    blobs:
        ``expert_id -> {tensor_key: [(shard_path, shard_file_key)]}`` from
        :meth:`SafetensorsExpertStore.expert_blobs`. Each tensor's bytes are
        read from its shard on demand.
    device:
        Default torch device for ``gpu`` placement. Guessed from the torch
        available device if not given.
    """

    def __init__(
        self,
        blobs: dict[str, dict[str, list[tuple[Path, str]]]],
        device: str | None = None,
    ) -> None:
        self._blobs = blobs
        self._device = device
        # expert_id -> dict[tensor_key, ndarray|Tensor] resident in memory (gpu or cpu).
        self._resident_tensors: dict[str, dict[str, Any]] = {}
        # Track which tier each in-memory expert currently sits on.
        self._tier: dict[str, str] = {}

    @property
    def device(self) -> str:
        if self._device is not None:
            return self._device
        from kiln.utils.platform import torch_gpu_available

        if torch_gpu_available():
            return "cuda"
        return "cpu"

    def is_resident(self, expert_id: str, tier: str) -> bool:
        return self._tier.get(expert_id) == tier and expert_id in self._resident_tensors

    def move(self, expert: Expert, from_tier: str, to_tier: str) -> None:
        """Move ``expert`` between tiers (the :class:`Mover` contract).

        Idempotent: moving to a tier it is already on is a no-op. The
        ``from_tier`` argument is advisory (the bank tracks state it already
        knows) and only used for bookkeeping.
        """
        eid = expert.expert_id
        if self.is_resident(eid, to_tier):
            return
        if to_tier == _G_TIER:
            self._place_gpu(expert)
        elif to_tier == _C_TIER:
            self._place_cpu(expert)
        elif to_tier == _D_TIER:
            self._drop(expert)
        else:
            raise ValueError(f"unknown tier {to_tier!r}")
        self._tier[eid] = to_tier

    # -- placement ----------------------------------------------------------
    def _place_gpu(self, expert: Expert) -> None:
        tensors = self._load_tensors(expert)  # numpy dict
        import torch

        dev = torch.device(self.device)
        gpu = {key: torch.as_tensor(arr, device=dev) for key, arr in tensors.items()}
        self._resident_tensors[expert.expert_id] = gpu

    def _place_cpu(self, expert: Expert) -> None:
        # If already on GPU, pull back to CPU; else (re)load from shard as numpy.
        current = self._resident_tensors.get(expert.expert_id)
        if current is not None and self._tier.get(expert.expert_id) == _G_TIER:
            # Move torch tensors back to host; no torch import needed (tensor methods).
            cpu = {key: t.detach().cpu() for key, t in current.items()}
            self._resident_tensors[expert.expert_id] = cpu
        else:
            self._resident_tensors[expert.expert_id] = self._load_tensors(expert)

    def _drop(self, expert: Expert) -> None:
        self._resident_tensors.pop(expert.expert_id, None)

    # -- loading ------------------------------------------------------------
    def _load_tensors(self, expert: Expert) -> dict[str, Any]:
        blobs = self._blobs.get(expert.expert_id, {})
        if not blobs:
            raise KeyError(
                f"no safetensors blobs recorded for expert {expert.expert_id!r}"
            )
        from safetensors import safe_open

        out: dict[str, Any] = {}
        for key, locations in blobs.items():
            shard_path, shard_key = locations[0]
            with safe_open(str(shard_path), framework="numpy") as f:
                out[key] = f.get_tensor(shard_key)
        return out
