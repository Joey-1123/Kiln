"""Tests for elastic VRAM rebalance on the LFRU tier (V2)."""

from kiln.engine.cache_tier import LFRUTier


def _fill(tier: LFRUTier) -> None:
    for i in range(tier.capacity):
        tier.put(f"k{i}", i)


def test_rebalance_frees_coldest():
    tier = LFRUTier(capacity=4, promotion_threshold=2, trace=None)
    _fill(tier)
    evicted = tier.rebalance(keep_fraction=0.5)
    # capacity 4 * 0.5 = 2 → evict down to 2 resident
    assert evicted == 2
    assert tier.size == 2


def test_rebalance_keep_fraction_bounds():
    tier = LFRUTier(capacity=4, trace=None)
    try:
        tier.rebalance(keep_fraction=1.5)
        assert False, "expected ValueError"
    except ValueError:
        pass
