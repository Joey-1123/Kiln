"""V2 layer-streaming training — bound peak VRAM by streaming layers.

Loading a whole model into VRAM for fine-tuning is the dominant memory cost.
Layer-streaming loads one layer at a time, trains it, then unloads it before
moving to the next, keeping peak usage near a single layer instead of the full
model. The actual load/unload of weights is delegated to an injectable
``StreamableModel`` so the streaming orchestration is testable without a GPU.

Adapter save/load uses canonical key names so a streamed checkpoint can be
loaded into a non-streamed model and vice versa. The canonicalization strips
wrapper prefixes (``_orig_mod.``) and inner-module shims (``.inner.``) that appear
under DDP or streaming wrappers; this keeps every future streaming variant cheap.

Budget helpers are torch-free pure math; heavy model introspection is lazy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable

log = logging.getLogger(__name__)


@runtime_checkable
class StreamableModel(Protocol):
    """A model that can load/unload individual layers on demand."""

    num_layers: int

    def load_layer(self, index: int) -> None: ...

    def unload_layer(self, index: int) -> None: ...


LayerCallback = Callable[[int], None]


def canonical_key(key: str) -> str:
    """Map a possibly-wrapped parameter key to its canonical form.

    Strips ``_orig_mod.`` prefix added by ``torch.compile`` and ``.inner.``
    shims injected by streaming wrappers, mirroring the upstream reference
    canonicalization. The mapping is idempotent.
    """
    if key.startswith("_orig_mod."):
        key = key[len("_orig_mod.") :]
    key = key.replace(".inner.", ".")
    return key


def canonical_state_dict(state: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``state`` with canonical key names."""
    return {canonical_key(k): v for k, v in state.items()}


def canonical_named_params(named_params: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
    """Canonicalize a ``model.named_parameters()`` list in place."""
    return [(canonical_key(k), v) for k, v in named_params]


def assert_canonical_intersection(
    model_params: list[tuple[str, Any]],
    adapter_params: dict[str, Any],
) -> None:
    """Validate that at least one canonical adapter key intersects the model.

    Streaming and DDP wrappers can silently mismatch every key if the wrong
    wrapper path is used to enumerate parameters. A zero-overlap save is a
    silent data-loss bug, so this is a hard error.
    """
    model_keys = {canonical_key(k) for k, _ in model_params}
    adapter_keys = {canonical_key(k) for k in adapter_params}
    if model_keys.isdisjoint(adapter_keys):
        sample_m = sorted(model_keys)[:3]
        sample_a = sorted(adapter_keys)[:3]
        raise ValueError(
            "canonical key mismatch: adapter and model intersect on 0 keys; "
            f"model sample {sample_m!r}, adapter sample {sample_a!r}"
        )


@dataclass(frozen=True)
class StreamingEstimate:
    full_vram_bytes: int
    streaming_peak_bytes: int
    layers: int
    saved_bytes: int
    saved_fraction: float


def estimate_streaming_peak(
    full_vram_bytes: int,
    layers: int,
    overhead_bytes: int = 0,
) -> StreamingEstimate:
    """Estimate streaming peak vs full-resident VRAM.

    The streaming peak is approximately one layer plus fixed overhead (embeddings,
    lm_head, optimizer shard for the active layer). The estimate is conservative
    and torch-free so it can gate ``layer_streaming`` before any model is loaded.
    """
    if layers <= 0:
        raise ValueError(f"layers must be >0, got {layers}")
    if full_vram_bytes <= 0:
        raise ValueError(f"full_vram_bytes must be >0, got {full_vram_bytes}")
    per_layer = full_vram_bytes // layers
    streaming_peak = per_layer + overhead_bytes
    saved = max(0, full_vram_bytes - streaming_peak)
    frac = saved / full_vram_bytes if full_vram_bytes else 0.0
    return StreamingEstimate(
        full_vram_bytes=full_vram_bytes,
        streaming_peak_bytes=streaming_peak,
        layers=layers,
        saved_bytes=saved,
        saved_fraction=frac,
    )


class LayerStreamer:
    """Iterates a model's layers, resident one at a time.

    Parameters
    ----------
    model:
        A :class:`StreamableModel` whose layers can be loaded/unloaded.
    on_layer:
        Called with each layer index while that layer is the only one resident.
    """

    def __init__(self, model: StreamableModel, on_layer: LayerCallback) -> None:
        if model.num_layers <= 0:
            raise ValueError(f"model.num_layers must be >0, got {model.num_layers}")
        self._model = model
        self._on_layer = on_layer
        self.visited: list[int] = []

    def run(self) -> None:
        """Stream every layer: load → callback → unload."""
        for i in range(self._model.num_layers):
            self._model.load_layer(i)
            try:
                self._on_layer(i)
            finally:
                try:
                    self._model.unload_layer(i)
                except Exception:
                    log.exception("unload_layer %d failed", i)
                    raise
            self.visited.append(i)

    @property
    def peak_resident_layers(self) -> int:
        """Layers resident at peak — always 1 by construction."""
        return 1

    @property
    def total_layers(self) -> int:
        return self._model.num_layers


def save_adapter_canonical(
    state_dict: dict[str, Any],
    save_fn: Callable[[dict[str, Any]], None],
) -> None:
    """Save an adapter state dict through canonical key mapping."""
    canonical = canonical_state_dict(state_dict)
    save_fn(canonical)


def load_adapter_canonical(
    state_dict: dict[str, Any],
    load_fn: Callable[[str, Any], None],
) -> None:
    """Load adapter weights keyed by canonical names into the caller's loader."""
    for k, v in state_dict.items():
        load_fn(canonical_key(k), v)
