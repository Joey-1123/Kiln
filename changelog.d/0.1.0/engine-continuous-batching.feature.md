V2 — continuous batching scheduler (`src/kiln/engine/batching.py`). Admits in-flight
requests into batches up to a max size in arrival order, releasing finished ones
and admitting new ones as capacity frees. Deterministic and unit-tested without a GPU.
