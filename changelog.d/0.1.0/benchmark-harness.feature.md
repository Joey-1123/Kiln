V2 — serving benchmark harness (`kiln benchmark` + `src/kiln/benchmarks/`).
Loads a model into the chosen backend and measures real TTFT / tokens-per-second
/ memory bars through the HTTP serving surface (the `MetricsCollector` the same
`/v1/metrics` the dashboard reads). Compulsory: requires `--model`, selects a
registered backend, and exits 1 (never silently skips) when the model cannot
load. Torch-free; the llama.cpp CPU and torch CUDA backends both supported.
Unit-tested (serialization, rendering, JSON, loud-failure paths).