V2 (A10) — `kiln tune` self-calibration command + GPU-UUID-keyed measurement
  cache. `kiln tune` measures CUDA memory bandwidth (lazy torch, no torch-free
  zone leak) and writes a `<key>.json` into `$XDG_CACHE_HOME/kiln/measurements`,
  reused by `plan` for prod backend selection.
Stale entries are disqualified by timestamp (OutputDrift guard). Falls back to
a conservative `cpu` recommendation when torch/CUDA is absent.
