# V2 — 14B everywhere + smarter memory — Execution Plan

Derived from locked plan §6 V2. One commit per milestone, pushed after tests+ruff pass.

## Milestone inventory

| # | Slice | Scope | Commit after |
|---|---|---|---|
| V2-1 | **Layer-streaming** opt-in | `trainer` adapter save/load canonical keys, `layer_streaming` bool wired, memory math in `utils/budget.py`, `config/schema.py` already has field | Commit + push |
| V2-2 | **Continuous batching + decode fusion** | Wire `ContinuousBatcher` + `DecodeScheduler` into `Engine` loop; first Triton kernel behind `BackendInfo` flag; parity oracle vs HF | Commit + push |
| V2-3 | **CPU↔GPU offload banks** | Wire `ExpertBank` + `LFRUTier` + `cache_tier.rebalance` into CUDA backend selection; `MoESpec` validation; pure-Python first, no torch until V2-2 kernel lands | Commit + push |
| V2-4 | **GPTQ/AWQ + quant menu** | Finish `quant/apply.py` ↔ `quant/quantize.py` ↔ `cli quantize` ↔ serve `quantization` field; GGUF AWQ path | Commit + push |
| V2-5 | **Elastic VRAM + metrics + dashboard** | `POST /v1/cache/rebuild` (free-before-alloc, baseline_free/weights_bytes), `engine/metrics.py` → `GET /v1/metrics` bars, web dashboard tok/s + TTFT | Commit + push |
| V2-6 | **Recipes + adapter registry + hot-cache** | `recipes/catalog.py` + `adapter_registry` with lineage, `learned hot-cache` pin list, `tune` measurement cache reuse | Commit + push |
| V2-7 | **xgrammar constrained decoding** | `grammar` field end-to-end (gateway → engine → backend sampling), `ToolDefinition` validation, fallback when xgrammar missing | Commit + push |
| V2-8 | **Colibri mining tail** | `route_trace` telemetry wired, PILOT prefetch behind capability flag (OFF by default, measurement-gated), `expert_budget` decode-only guard enforced | Commit + push |
| V2-9 | **Parity oracle gate** | A8 hard gate: CPU(GPU)↔GGUF logit-window + task-level equivalence at capacities {1,2,8}, CI blocking job, fixtures gen vs consume split | Commit + push |

## Prereqs already on master
- `tier.h` LFRU (~100 LOC) → `cache_tier.py`
- `route_trace` (~300 LOC) → `route_trace.py`
- `Batcher` / `DecodeScheduler` / `ExpertBank` / `MoESpec` / `MetricsCollector` stubs are real implementations, currently unwired from `Engine`
- `tune` self-calibration + `doctor/plan` triad exists
- Parity `parity.py` harness exists (expand to gate)

## Rules per milestone
- Lazy heavy imports inside functions; keep `test_cli_startup_is_light.py` green
- `rich.console.Console` output, `utils/paths.py` containment, `utils/platform.py` only `sys.platform` branch, exit codes via `utils/exitcodes.py`
- Changelog fragment per commit under `changelog.d/0.1.1/` (bump on first V2-1)
- `ruff check` + `pytest` before every push
