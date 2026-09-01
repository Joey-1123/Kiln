# Benchmarks

Memory-bound regression harness (plan §8.5). Published as-written — failures included.

## Run

```bash
uv run python -m benchmarks.runner --smoke
uv run python -m benchmarks.runner --iterations 3 --jsonl benchmarks/results/run.jsonl --markdown benchmarks/results/report.md
```

## Suite

| bench | what it measures |
|-------|------------------|
| `budget_estimate` | `utils.budget.estimate_vram_bytes` (pure math, 8B QLoRA) |
| `lfru_hit` | `LFRUTier.get/mark_access` hit path |
| `lfru_rebalance` | `LFRUTier.rebalance` eviction |
| `batcher_step` | `ContinuousBatcher.step/complete` |
| `decode_scheduler` | `DecodeScheduler.run` (uncaptured) |
| `decode_captured` | `DecodeScheduler.capture` replay |
| `queue_transport` | `QueueTransport.put/get` asyncio round-trip |
| `metrics_collector` | `MetricsCollector` TTFT/tok/s aggregation |

All benches are torch-free so PR CI can run them. `--smoke` runs a 3-bench subset.

## Results

`benchmarks/results/` is gitignored. CI uploads `run.jsonl` as an artifact; the parity oracle gate (A8) is the only blocking check. Rejected optimizations are recorded here with measurements per colibri ledger culture.
