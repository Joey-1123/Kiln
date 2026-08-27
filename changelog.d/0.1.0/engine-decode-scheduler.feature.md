V2 — graph-capturable decode scheduler (`src/kiln/engine/decode_scheduler.py`). Models
the fixed-address decode loop as a fixed sequence of steps so it can be captured
once and replayed as a static graph (a real kernel backend would wrap `capture()`
in `torch.cuda.graph`). Decode-only expert-trim guard still applies. Pure-Python
and unit-tested without a GPU.
