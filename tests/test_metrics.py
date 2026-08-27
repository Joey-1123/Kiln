"""Tests for serving metrics (V2)."""

from kiln.engine.metrics import MetricsCollector, summarise


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
