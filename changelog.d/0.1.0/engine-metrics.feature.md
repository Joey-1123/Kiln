V2 — serving metrics collector (`src/kiln/engine/metrics.py`). Records per-request
TTFT and tokens-per-second (injectable clock) and aggregates for the dashboard.
Torch-free; feeds the memory/tok-s bars without touching the heavy path.
