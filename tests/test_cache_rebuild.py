"""End-to-end V2-5 tests: runtime /v1/cache/rebuild + elastic VRAM metrics.

Drives the real full stack — HTTP gateway → engine loop → OffloadCoordinator →
memory bars in /v1/metrics — over in-process transports (the same seam the
single-process CLI serve uses), with no torch/CUDA involved.
"""

from kiln.engine.engine import Engine
from kiln.engine.gateway import _response_loop, create_gateway
from kiln.engine.messages import QueueTransport
from kiln.engine.metrics import MemoryBars
from kiln.engine.moe_spec import MoESpec


def _spec(n=4, dim=8, layers=2) -> MoESpec:
    return MoESpec(num_experts=n, expert_dim=dim, layers=layers)


def _offload_bars(eng: Engine):
    def _snapshot() -> MemoryBars:
        coord = eng.offload
        if coord is None:
            return MemoryBars()
        stats = coord.stats()
        return MemoryBars(
            gpu_used_bytes=stats.gpu_used_bytes,
            gpu_capacity_bytes=stats.gpu_capacity_bytes,
            resident_experts=stats.resident_experts,
            registered_experts=stats.registered_experts,
            phase=stats.phase,
        )

    return _snapshot


async def test_cache_rebuild_end_to_end():
    import asyncio

    import httpx
    from httpx import ASGITransport

    engine_out = QueueTransport()
    gw_out = QueueTransport()
    engine = Engine(gateway_transport=gw_out, engine_transport=engine_out)

    # Provision an offload coordinator and resident experts, mimicking a
    # freshly-loaded MoE model mid-decode (expert trimming is decode-only).
    coord = engine.init_offload(_spec(), gpu_capacity_bytes=100, strategy="offload")
    coord.begin_decode()
    for eid in ["l0.e0", "l0.e1", "l0.e2", "l1.e0"]:
        coord.ensure_experts([eid])
    assert coord.stats().resident_experts >= 3

    app = create_gateway(
        transport=gw_out,
        model_name="moe-demo",
        response_transport=engine_out,
        offload_stats=_offload_bars(engine),
    )

    engine_task = asyncio.create_task(engine.run())
    listener = asyncio.create_task(_response_loop(engine_out, app.state))
    try:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as c:
            # Rebalance down to a small keep_fraction so something is evicted.
            r = await asyncio.wait_for(
                c.post("/v1/cache/rebuild", json={"keep_fraction": 0.25}),
                timeout=10,
            )
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "rebalanced"
            assert body["registered"] == coord.stats().registered_experts
            assert body["gpu_capacity_bytes"] == 100
            assert body["evicted"] >= 1
            assert body["resident"] < coord.stats().registered_experts

            # /v1/metrics now reports the post-rebalance residency.
            m = await asyncio.wait_for(c.get("/v1/metrics"), timeout=10)
            assert m.status_code == 200
            mb = m.json()
            assert mb["gpu_capacity_bytes"] == float(100)
            assert mb["registered_experts"] == float(coord.stats().registered_experts)
            assert mb["resident_experts"] == float(coord.stats().resident_experts)
            assert mb["gpu_used_bytes"] > 0
    finally:
        engine.stop()
        engine_task.cancel()
        listener.cancel()


async def test_cache_rebuild_validation_end_to_end():
    import asyncio

    import httpx
    from httpx import ASGITransport

    engine_out = QueueTransport()
    gw_out = QueueTransport()
    engine = Engine(gateway_transport=gw_out, engine_transport=engine_out)
    app = create_gateway(
        transport=gw_out,
        model_name="m",
        response_transport=engine_out,
        offload_stats=_offload_bars(engine),
    )
    engine_task = asyncio.create_task(engine.run())
    listener = asyncio.create_task(_response_loop(engine_out, app.state))
    try:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as c:
            for bad in (1.5, -0.1, "x"):
                r = await asyncio.wait_for(
                    c.post("/v1/cache/rebuild", json={"keep_fraction": bad}),
                    timeout=10,
                )
                assert r.status_code == 400
                assert "invalid_keep_fraction" in r.text
    finally:
        engine.stop()
        engine_task.cancel()
        listener.cancel()
