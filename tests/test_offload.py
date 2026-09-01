import pytest

from kiln.engine.expert_bank import Strategy
from kiln.engine.expert_budget import DecodeOnlyError
from kiln.engine.moe_spec import MoESpec
from kiln.engine.offload import OffloadCoordinator


def _spec(n=4, dim=8, layers=2) -> MoESpec:
    return MoESpec(num_experts=n, expert_dim=dim, layers=layers)


def test_coordinator_lifecycle_and_stats():
    c = OffloadCoordinator(_spec(), gpu_capacity_bytes=10_000, strategy=Strategy.offload)
    assert c.phase == "idle"
    assert c.stats().phase == "idle"
    assert c.stats().registered_experts == 8
    assert c.stats().resident_experts == 0
    c.begin_prefill()
    assert c.phase == "prefill"
    c.begin_decode()
    assert c.phase == "decode"
    assert c.budget.phase == "decode"
    c.end_phase()
    assert c.phase == "idle"
    assert c.budget.phase == "idle"


def test_ensure_experts_decode_only_guard():
    c = OffloadCoordinator(_spec(), gpu_capacity_bytes=8 << 30, strategy=Strategy.offload)
    c.begin_prefill()
    with pytest.raises(DecodeOnlyError):
        c.ensure_experts(["l0.e0"])
    c.begin_decode()
    c.ensure_experts(["l0.e0"])
    assert c.bank.is_resident("l0.e0")
    assert "l0.e0" in c.tier
    c.end_phase()
    assert c.phase == "idle"


def test_ensure_experts_unknown_raises():
    c = OffloadCoordinator(_spec(), gpu_capacity_bytes=8 << 30)
    c.begin_decode()
    with pytest.raises(KeyError):
        c.ensure_experts(["nope"])


def test_ensure_experts_resident_in_prefill_allowed():
    c = OffloadCoordinator(_spec(), gpu_capacity_bytes=8 << 30)
    c.begin_decode()
    c.ensure_experts(["l0.e1"])
    c.end_phase()
    c.begin_prefill()
    c.ensure_experts(["l0.e1"])
    assert c.bank.is_resident("l0.e1")


def test_trim_delegates_to_budget_and_guard():
    c = OffloadCoordinator(_spec(), gpu_capacity_bytes=8 << 30)
    c.begin_prefill()
    with pytest.raises(DecodeOnlyError):
        c.trim_experts([0])
    c.begin_decode()
    c.trim_experts([0])
    assert 0 not in c.budget.active


def test_rebalance_delegates_to_tier():
    c = OffloadCoordinator(_spec(), tier_capacity=4)
    c.begin_decode()
    for eid in ["l0.e0", "l0.e1", "l0.e2", "l1.e0"]:
        c.ensure_experts([eid])
    evicted = c.rebalance(keep_fraction=0.5)
    assert evicted >= 1
    assert c.tier.size == 2


def test_mover_injected_via_build_expert_bank():
    moves: list[tuple] = []

    def mover(exp, frm, to):
        moves.append((exp.expert_id, frm, to))

    c = OffloadCoordinator(_spec(), gpu_capacity_bytes=8 << 30, mover=mover)
    c.begin_decode()
    c.ensure_experts(["l0.e0"])
    assert any(m[2] == "gpu" for m in moves)


def test_moe_spec_validation_rejected():
    with pytest.raises(ValueError):
        OffloadCoordinator(MoESpec(num_experts=0, expert_dim=8, layers=1))


def test_engine_init_offload_wiring():
    from kiln.engine.engine import Engine
    from kiln.engine.messages import QueueTransport

    e = Engine(gateway_transport=QueueTransport(), engine_transport=QueueTransport())
    assert e.offload is None
    coord = e.init_offload(_spec(), gpu_capacity_bytes=8 << 30, strategy="offload")
    assert e.offload is coord
    assert coord.stats().registered_experts == 8
    assert coord.strategy == Strategy.offload


def test_build_expert_bank_accepts_mover():
    from kiln.engine.moe_spec import build_expert_bank

    moves: list[tuple] = []

    def mover(exp, frm, to):
        moves.append((exp.expert_id, frm, to))

    bank = build_expert_bank(_spec(), mover=mover, gpu_capacity_bytes=1_000)
    bank.enter_decode()
    bank.ensure_resident(bank.experts["l0.e0"])
    assert any(m[0] == "l0.e0" for m in moves)


async def test_engine_cache_rebuild_handler():
    import asyncio

    from kiln.engine.engine import Engine
    from kiln.engine.messages import (
        CacheRebuildRequest,
        CacheRebuildResponse,
        GenerateError,
        QueueTransport,
    )

    gw_to_engine = QueueTransport()
    eng_to_gw = QueueTransport()
    e = Engine(gateway_transport=gw_to_engine, engine_transport=eng_to_gw)

    # No coordinator yet -> no_offload error.
    await e._dispatch(CacheRebuildRequest(request_id="c0", keep_fraction=0.5))
    err = await asyncio.wait_for(eng_to_gw.get(), timeout=2)
    assert isinstance(err, GenerateError)
    assert err.error_code == "no_offload"

    # Wire an offload coordinator and make some experts resident.
    coord = e.init_offload(_spec(), gpu_capacity_bytes=10_000, strategy="offload")
    coord.begin_decode()
    coord.ensure_experts(["l0.e0", "l0.e1", "l0.e2"])
    coord.end_phase()
    assert coord.stats().resident_experts >= 3

    # Rebalance to a small keep_fraction evicts residents and reports stats.
    await e._dispatch(CacheRebuildRequest(request_id="c1", keep_fraction=0.25))
    resp = await asyncio.wait_for(eng_to_gw.get(), timeout=2)
    assert isinstance(resp, CacheRebuildResponse)
    assert resp.request_id == "c1"
    assert resp.registered == coord.stats().registered_experts
    assert resp.gpu_capacity_bytes == 10_000
    assert resp.phase == coord.phase
