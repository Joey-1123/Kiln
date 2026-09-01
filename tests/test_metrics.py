"""Tests for serving metrics (V2)."""

from kiln.engine.metrics import MemoryBars, MetricsCollector, summarise
from kiln.engine.offload import OffloadStats


def _make() -> tuple[MetricsCollector, list[float], list[float]]:
    ticks = [0.0]
    clock = lambda: ticks[0]  # noqa: E731
    return MetricsCollector(clock=clock), ticks, []


def test_ttft_and_tps():
    mc, ticks, _ = _make()
    mc.start("r1")
    ticks[0] = 1.0
    mc.token("r1")  # first token at t=1 → TTFT = 1.0
    ticks[0] = 3.0
    mc.token("r1")
    mc.token("r1")  # 3 tokens total between t=1 and t=3 → 3 tok / 2s = 1.5 tok/s
    ticks[0] = 3.0
    mc.finish("r1")
    rec = mc.get("r1")
    assert rec.ttft == 1.0
    assert rec.token_count == 3
    assert rec.tokens_per_second == 1.5


def test_summarise_empty():
    assert summarise([])["requests"] == 0.0


def test_summarise_without_memory_keeps_stable_shape():
    out = summarise([])
    for key in (
        "gpu_used_bytes",
        "gpu_capacity_bytes",
        "resident_experts",
        "registered_experts",
        "phase",
    ):
        assert key in out
    assert out["gpu_used_bytes"] == 0.0
    assert out["phase"] == ""


def test_summarise_includes_memory_bars():
    mem = MemoryBars(
        gpu_used_bytes=5 << 30,
        gpu_capacity_bytes=8 << 30,
        resident_experts=6,
        registered_experts=12,
        phase="decode",
    )
    out = summarise([], memory=mem)
    assert out["gpu_used_bytes"] == float(5 << 30)
    assert out["gpu_capacity_bytes"] == float(8 << 30)
    assert out["resident_experts"] == 6.0
    assert out["registered_experts"] == 12.0
    assert out["phase"] == "decode"


def test_memory_bars_from_offload_stats():
    stats = OffloadStats(
        gpu_used_bytes=4 << 30,
        gpu_capacity_bytes=8 << 30,
        resident_experts=3,
        registered_experts=16,
        phase="prefill",
    )
    bars = MemoryBars(
        gpu_used_bytes=stats.gpu_used_bytes,
        gpu_capacity_bytes=stats.gpu_capacity_bytes,
        resident_experts=stats.resident_experts,
        registered_experts=stats.registered_experts,
        phase=stats.phase,
    )
    assert bars.resident_experts == 3
    assert bars.phase == "prefill"
