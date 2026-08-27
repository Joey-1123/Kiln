"""Tests for the MoE expert bank offload/hybrid placement (plan A9)."""

import pytest

from kiln.engine.expert_bank import Expert, ExpertBank, Strategy
from kiln.engine.expert_budget import DecodeOnlyError


def _expert(eid: str, size: int = 100) -> Expert:
    return Expert(expert_id=eid, size_bytes=size)


def test_offload_strategy_spills_to_cpu():
    bank = ExpertBank(gpu_capacity_bytes=250, strategy=Strategy.offload)
    # Fill GPU exactly: 2 experts * 100 = 200, room for a third would exceed 250.
    for eid in ("a", "b"):
        bank.ensure_resident(_expert(eid))
    assert set(bank.resident_ids) == {"a", "b"}
    assert bank.gpu_used_bytes == 200

    # Third expert forces an eviction (decode phase required to trim).
    bank.enter_decode()
    bank.ensure_resident(_expert("c"))
    # One of a/b spilled to cpu; c is resident.
    assert "c" in bank.resident_ids
    assert len(bank.resident_ids) == 2
    moves = {(m[0].expert_id, m[1], m[2]) for m in bank.moves}
    assert ("c", "load", "gpu") in moves
    # Some expert moved gpu -> cpu
    assert any(to_ == "cpu" for (_e, _f, to_) in bank.moves if _f == "gpu")


def test_hybrid_strategy_spills_to_disk():
    bank = ExpertBank(gpu_capacity_bytes=150, strategy=Strategy.hybrid)
    bank.enter_decode()
    for eid in ("a", "b", "c"):
        bank.ensure_resident(_expert(eid))  # third forces gpu->disk (hybrid)
    assert any(to_ == "disk" for (_e, _f, to_) in bank.moves if _f == "gpu")


def test_cpu_strategy_never_resident():
    bank = ExpertBank(gpu_capacity_bytes=10, strategy=Strategy.cpu)
    bank.ensure_resident(_expert("a", size=999))
    assert bank.resident_ids == []
    assert bank.gpu_used_bytes == 0
    assert ("a", "load", "cpu") in {(m[0].expert_id, m[1], m[2]) for m in bank.moves}


def test_decode_only_guard_blocks_trim_in_prefill():
    bank = ExpertBank(gpu_capacity_bytes=100, strategy=Strategy.offload)
    bank.ensure_resident(_expert("a"))  # fills GPU; not decode yet
    with pytest.raises(DecodeOnlyError):
        bank.ensure_resident(_expert("b"))  # would need to evict a
    # In decode phase it is allowed.
    bank.enter_decode()
    bank.ensure_resident(_expert("b"))
    assert "b" in bank.resident_ids


def test_resident_touch_promotes_no_evict():
    bank = ExpertBank(gpu_capacity_bytes=200, strategy=Strategy.offload)
    bank.enter_decode()
    bank.ensure_resident(_expert("a"))
    bank.ensure_resident(_expert("b"))
    # Re-ensure a: should be a touch, not a reload.
    before = len(bank.moves)
    bank.ensure_resident(_expert("a"))
    assert len(bank.moves) == before  # no move recorded
    assert bank.is_resident("a")
