# Benchmarks

Memory-bound regression harness (plan §8.5). Published as-written — failures included, rejected optimizations recorded with measurements per colibri ledger culture.

## Harness

```
benchmarks/
  __init__.py         # re-exports run_suite / BenchmarkResult
  suite.py            # 8 benches — torch-free, GPU-optional
  runner.py           # timing, JSONL + markdown output
  results/            # gitignored JSONL + markdown reports
```

| bench | what it measures |
|-------|------------------|
| `budget_estimate` | `utils.budget.estimate_vram_bytes` (8B QLoRA) |
| `lfru_hit` | `LFRUTier.get/mark_access` hit path |
| `lfru_rebalance` | `LFRUTier.rebalance` eviction |
| `batcher_step` | `ContinuousBatcher.step/complete` |
| `decode_scheduler` | `DecodeScheduler.run` (uncaptured) |
| `decode_captured` | `DecodeScheduler.capture` replay |
| `queue_transport` | `QueueTransport.put/get` asyncio round-trip |
| `metrics_collector` | `MetricsCollector` TTFT/tok/s aggregation |

All benches are torch-free so PR CI can run them. `--smoke` runs a 3-bench subset (`budget_estimate`, `lfru_hit`, `queue_transport`).

## Running

```bash
uv run python -m benchmarks.runner --smoke
uv run python -m benchmarks.runner --iterations 3 --jsonl benchmarks/results/run.jsonl --markdown benchmarks/results/report.md
```

## CI

GPU smoke runs nightly on a self-hosted runner; PR CI covers logic + CPU paths. Results are published as artifacts, never gated as pass/fail except for the parity oracle release gate (A8).

## References

- Plan §8.1 (oracle), §8.5 (benchmarks as-written), §11 amendments A8–A10
- `specs/references-analysis.md` — ledger culture notes from colibri
