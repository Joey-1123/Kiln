"""Tests for layer-streaming training (plan D5)."""

from kiln.trainer.layer_stream import LayerStreamer


class _FakeModel:
    def __init__(self, n: int) -> None:
        self.num_layers = n
        self.resident: set[int] = set()
        self.peak = 0

    def load_layer(self, i: int) -> None:
        assert i not in self.resident, f"layer {i} already resident (not streamed)"
        self.resident.add(i)
        self.peak = max(self.peak, len(self.resident))

    def unload_layer(self, i: int) -> None:
        self.resident.discard(i)


def test_stream_visits_each_layer_once():
    model = _FakeModel(4)
    seen: list[int] = []
    streamer = LayerStreamer(model, on_layer=seen.append)
    streamer.run()
    assert seen == [0, 1, 2, 3]
    assert streamer.total_layers == 4


def test_stream_keeps_peak_single_layer():
    model = _FakeModel(5)
    streamer = LayerStreamer(model, on_layer=lambda i: None)
    streamer.run()
    # Only one layer resident at a time → peak VRAM ~= one layer.
    assert model.peak == 1
    assert streamer.peak_resident_layers == 1


def test_stream_unloads_after_callback():
    model = _FakeModel(3)
    streamer = LayerStreamer(model, on_layer=lambda i: None)
    streamer.run()
    assert model.resident == set()  # all unloaded at end
