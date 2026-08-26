# Milestone 5 — Serve-anywhere

- Added `kiln export-gguf`: auto-downloads llama.cpp, converts merged HF models to quantized GGUF (Q4_K_M, Q5_K_M, Q8_0, F16)
- Added `kiln doctor`: system health checks with quick mode (deps/GPU/RAM) and deep mode (engine binaries), JSON output
- Added `kiln plan`: hardware recommendations with backend/quantization suggestions, optional config file writing
- CLI: `export-gguf`, `doctor --deep/--json`, `plan --json/--write-config` commands live
