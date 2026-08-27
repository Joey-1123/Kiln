V2 (D5) — layer-streaming training (`src/kiln/trainer/layer_stream.py`). A
`LayerStreamer` loads one model layer at a time, trains it, then unloads it,
keeping peak VRAM near a single layer. Opt-in via `training.layer_streaming: bool`
in the config schema. Weight load/unload is delegated to an injectable
`StreamableModel` so the orchestration is unit-tested without a GPU.
