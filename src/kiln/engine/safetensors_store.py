"""Safetensors-backed expert store (plan V3 / B6).

Builds the real expert topology for an MoE model from its ``.safetensors``
shards, torch-free. It reads only the safetensors headers (via
``safetensors.numpy`` / ``safe_open(framework="numpy")``), derives each
expert's tensor keys and byte size from the shard metadata, and hands the
descriptors to an :class:`~kiln.engine.expert_bank.ExpertBank`.

Why torch-free here
-------------------
The store only needs the *index* (which tensor lives in which shard, its
shape, its dtype) to size experts and to know where their weights are. That is
pure metadata; loading actual tensors onto a device is the
:class:`~kiln.engine.expert_mover.TorchExpertMover`'s job, which lazy-imports
torch. Keeping this module free of torch means the fast torch-free control
plane never drags the heavy path in just to read a header.

Shards are resolved the HuggingFace way: a single ``<prefix>.safetensors``
file, or a sharded model described by ``<prefix>.safetensors.index.json`` whose
``weight_map`` maps each tensor name to its shard file.

Tensor -> expert mapping
------------------------
Expert assignment is a configurable predicate so it works across architectures.
The default resolver parses the common MoE weight naming::

    layers.<L>.experts.<E>.<proj>.weight  ->  l<L>.e<E>

Only the projection weights that define an expert's shape (``up_proj`` /
``down_proj`` / ``gate_proj``) are registered per expert; ``size_bytes`` is the
sum over all matching tensors under that expert, and ``dims`` is the row count
of the expert's projection weight.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional

from kiln.engine.expert_bank import Expert, ExpertBank

# Canonical safetensors dtype code -> bytes per element.
_DTYPE_BYTES = {
    "F32": 4,
    "F16": 2,
    "BF16": 2,
    "F64": 8,
    "I64": 8,
    "I32": 4,
    "I16": 2,
    "I8": 1,
    "U8": 1,
    "BOOL": 1,
}

# Default convention: layers.<L>.experts.<E>.<proj>.weight
_EXPERT_KEY_RE = re.compile(r"layers\.(?P<layer>\d+)\.experts\.(?P<expert>\d+)\.")

# Projection weights that carry the expert's row count.
_SHAPE_PROJS = ("up_proj", "down_proj", "gate_proj")


class SafetensorsExpertStore:
    """Resolve a model directory's safetensors shards into an expert topology.

    Parameters
    ----------
    model_dir:
        Directory containing one ``*.safetensors`` file, or a sharded model
        with ``*.safetensors.index.json``.
    resolver:
        Optional callable mapping a tensor key to ``(expert_id, layer)`` or
        ``None`` (not an expert). Defaults to HFs MoE naming above.
    """

    def __init__(
        self,
        model_dir: str | Path,
        resolver: Optional[Callable[[str], tuple[str, int] | None]] = None,
    ) -> None:
        self._root = Path(model_dir)
        self._resolver = resolver or _default_resolver
        self._weight_map: Optional[dict[str, str]] = None
        self._shard_files: list[Path] = []
        self._resolve_shards()

    # -- discovery ----------------------------------------------------------
    def _resolve_shards(self) -> None:
        """Fill ``_shard_files`` and ``_weight_map`` from the model layout."""
        if not self._root.is_dir():
            raise FileNotFoundError(f"model dir does not exist: {self._root}")

        weight_map = self._read_weight_map()
        if weight_map is not None:
            shard_names = sorted({str(v) for v in weight_map.values()})
            files = [self._root / name for name in shard_names]
            for f in files:
                if not f.is_file():
                    raise FileNotFoundError(f"shard listed in index does not exist: {f}")
            self._weight_map = weight_map
            self._shard_files = files
            return

        shards = sorted(self._root.glob("*.safetensors"))
        if not shards:
            raise FileNotFoundError(
                f"no .safetensors files or *.safetensors.index.json in {self._root}"
            )
        self._shard_files = shards

    def _read_weight_map(self) -> Optional[dict[str, str]]:
        """Return the HF shard index ``weight_map`` if an index file exists."""
        for idx in self._root.glob("*.safetensors.index.json"):
            data = json.loads(idx.read_text(encoding="utf-8"))
            wm = data.get("weight_map")
            if isinstance(wm, dict):
                return {str(k): str(v) for k, v in wm.items()}
        return None

    # -- topology -----------------------------------------------------------
    def expert_blobs(self) -> dict[str, dict[str, list[tuple[Path, str]]]]:
        """Map ``expert_id -> {tensor_key: [(shard_path, shard_file_key)]}``.

        Keys map to the concrete shard they live in so the mover can fetch the
        real tensor bytes later. Building this is metadata-only (torch-free).
        """
        blobs: dict[str, dict[str, list[tuple[Path, str]]]] = {}
        for shard in self._shard_files:
            from safetensors import safe_open

            with safe_open(str(shard), framework="numpy") as f:
                for key in f.keys():
                    mapped = self._resolver(key)
                    if mapped is None:
                        continue
                    expert_id, _layer = mapped
                    blobs.setdefault(expert_id, {}).setdefault(key, []).append(
                        (shard, key)
                    )
        return blobs

    def experts(self) -> list[Expert]:
        """Build :class:`Expert` descriptors with real byte sizes.

        ``size_bytes`` is the summed element count (from each tensor's shape
        and dtype) times the dtype size. ``dims`` is the row count of the
        expert's shape-bearing projection weight.
        """
        experts: dict[str, Expert] = {}
        for shard in self._shard_files:
            from safetensors import safe_open

            with safe_open(str(shard), framework="numpy") as f:
                for key in f.keys():
                    mapped = self._resolver(key)
                    if mapped is None:
                        continue
                    expert_id, layer = mapped
                    sl = f.get_slice(key)
                    nbytes = _tensor_bytes(sl.get_dtype(), list(sl.get_shape()))
                    if expert_id not in experts:
                        experts[expert_id] = Expert(
                            expert_id=expert_id,
                            size_bytes=nbytes,
                            layer=layer,
                            dims=_row_count(key, list(sl.get_shape())),
                        )
                    else:
                        e = experts[expert_id]
                        experts[expert_id] = Expert(
                            expert_id=e.expert_id,
                            size_bytes=e.size_bytes + nbytes,
                            layer=e.layer,
                            dims=max(e.dims, _row_count(key, list(sl.get_shape()))),
                        )
        if not experts:
            raise ValueError(
                f"no expert tensors found under the default resolver; "
                f"pass an explicit resolver for the architecture in {self._root}"
            )
        return list(experts.values())

    def populate(self, bank: ExpertBank) -> None:
        """Register every discovered expert into ``bank`` (CPU-side by default)."""
        for expert in self.experts():
            bank.register(expert)

    @property
    def shard_files(self) -> list[Path]:
        return list(self._shard_files)


def build_mover(store: SafetensorsExpertStore):
    """Return a real :class:`Mover` bound to ``store``'s shards.

    The returned callable moves an :class:`Expert` between ``gpu`` / ``cpu`` /
    ``disk`` by loading/releasing its tensors. Placement is delegated to
    :class:`~kiln.engine.expert_mover.TorchExpertMover`, which lazy-imports
    torch so this factory stays import-safe without it.
    """
    from kiln.engine.expert_mover import TorchExpertMover

    mover = TorchExpertMover(store.expert_blobs())
    return mover.move


def _default_resolver(key: str) -> tuple[str, int] | None:
    """Map ``layers.<L>.experts.<E>.<proj>.weight`` -> ``(l<L>.e<E>, L)``."""
    m = _EXPERT_KEY_RE.search(key)
    if m is None:
        return None
    layer = int(m.group("layer"))
    return f"l{layer}.e{int(m.group('expert'))}", layer


def _row_count(key: str, shape: list[int]) -> int:
    """Row count (first shape dim) for a shape-bearing projection key."""
    if any(f".{p}.weight" in key for p in _SHAPE_PROJS) and shape:
        return int(shape[0])
    return 0


def _tensor_bytes(dtype: str, shape: list[int]) -> int:
    """Bytes for a tensor given its safetensors dtype code and shape.

    Raises ``ValueError`` for an unimplemented dtype so a host store never
    silently mis-sizes an expert.
    """
    if dtype not in _DTYPE_BYTES:
        raise ValueError(f"unsupported safetensors dtype {dtype!r}")
    n = 1
    for d in shape:
        n *= int(d)
    return n * _DTYPE_BYTES[dtype]
