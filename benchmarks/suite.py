"""Benchmark suite — one callable per measured path.

Every bench is torch-free and GPU-optional so PR CI can run them.
GPU benches gate themselves on availability and report `skipped`.
"""

from __future__ import annotations

import asyncio

from kiln.engine.batching import ContinuousBatcher
from kiln.engine.cache_tier import LFRUTier
from kiln.engine.decode_scheduler import DecodeScheduler
from kiln.engine.messages import QueueTransport
from kiln.utils.budget import estimate_vram_bytes


def bench_budget() -> None:
    for _ in range(200):
        estimate_vram_bytes(
            param_count=8_000_000_000,
            lora_rank=16,
            lora_target_modules=6,
            batch_size=4,
            seq_len=2048,
            hidden_size=4096,
        )


def bench_lfru_hit() -> None:
    tier: LFRUTier[str] = LFRUTier(capacity=8)
    for i in range(16):
        tier.put(f"k{i}", f"v{i}")
    for _ in range(500):
        for i in range(8):
            tier.get(f"k{i+8}")
            tier.mark_access(f"k{i+8}")


def bench_lfru_rebalance() -> None:
    tier: LFRUTier[int] = LFRUTier(capacity=64)
    for i in range(64):
        tier.put(f"k{i}", i)
    for _ in range(100):
        tier.rebalance(keep_fraction=0.5)
        for i in range(32, 64):
            tier.put(f"k{i}", i)


def bench_batcher() -> None:
    b: ContinuousBatcher[str] = ContinuousBatcher(max_batch=8)
    for i in range(32):
        b.submit(f"r{i}")
    for _ in range(200):
        batch = b.step()
        for r in batch:
            b.complete(r)
        if b.pending == 0:
            for i in range(8):
                b.submit(f"r{i}")


def bench_decode_scheduler() -> None:
    def step(s: dict) -> dict:
        s["x"] = s.get("x", 0) + 1
        return s

    sched = DecodeScheduler(steps=[step, step], max_steps=64)
    for _ in range(100):
        sched.run({"x": 0}, n_steps=16)


def bench_decode_captured() -> None:
    def step(s: dict) -> dict:
        s["x"] = s.get("x", 0) + 1
        return s

    sched = DecodeScheduler(steps=[step], max_steps=64)
    replay = sched.capture()
    for _ in range(200):
        replay({"x": 0})


def bench_queue_transport() -> None:
    async def _run() -> None:
        t: QueueTransport = QueueTransport()
        for _ in range(200):
            await t.put({"v": 1})
            await t.get()

    asyncio.run(_run())


def bench_metrics() -> None:
    from kiln.engine.metrics import MetricsCollector

    t = 0.0

    def clock() -> float:
        return t

    c = MetricsCollector(clock=lambda: t)
    for i in range(200):
        rid = f"r{i}"
        c.start(rid)
        t += 0.01
        c.first_token(rid)
        for _ in range(8):
            c.token(rid)
            t += 0.005
        c.finish(rid)
    c.snapshot()


SUITE: list[tuple[str, callable]] = [
    ("budget_estimate", bench_budget),
    ("lfru_hit", bench_lfru_hit),
    ("lfru_rebalance", bench_lfru_rebalance),
    ("batcher_step", bench_batcher),
    ("decode_scheduler", bench_decode_scheduler),
    ("decode_captured", bench_decode_captured),
    ("queue_transport", bench_queue_transport),
    ("metrics_collector", bench_metrics),
]

SMOKE = {"budget_estimate", "lfru_hit", "queue_transport"}
