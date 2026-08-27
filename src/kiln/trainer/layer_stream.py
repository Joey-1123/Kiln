"""V2 layer-streaming training (plan D5) — bound peak VRAM by streaming layers.

Loading a whole model into VRAM for fine-tuning is the dominant memory cost.
Layer-streaming loads one layer at a time, trains it, then unloads it before
moving to the next, keeping peak usage near a single layer instead of the full
model. The actual load/unload of weights is delegated to an injectable
``StreamableModel`` so the streaming orchestration is testable without a GPU.
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable


@runtime_checkable
class StreamableModel(Protocol):
    """A model that can load/unload individual layers on demand."""

    num_layers: int

    def load_layer(self, index: int) -> None: ...

    def unload_layer(self, index: int) -> None: ...


# A per-layer training callback: receives the index of the layer currently resident.
LayerCallback = Callable[[int], None]


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
                self._model.unload_layer(i)
            self.visited.append(i)

    @property
    def peak_resident_layers(self) -> int:
        """Layers resident at peak — always 1 by construction."""
        return 1

    @property
    def total_layers(self) -> int:
        return self._model.num_layers
