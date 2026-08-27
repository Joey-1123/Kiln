"""Tests for the V2 LFRU memory tier (plan A5)."""

from __future__ import annotations

import pytest

from kiln.engine.cache_tier import LFRUTier


def test_capacity_enforced_and_cold_lfu_eviction() -> None:
    tier = LFRUTier(capacity=2)
    tier.put("a", 1)
    tier.put("b", 2)
    tier.put("c", 3)  # over capacity -> evict
    # 'a' and 'b' both freq 1 (FIFO) -> 'a' evicted first
    assert "a" not in tier
    assert tier.size == 2
    assert set(tier.keys()) == {"b", "c"}


def test_cold_evicts_lowest_frequency() -> None:
    tier = LFRUTier(capacity=2)
    tier.put("a", 1)
    tier.put("b", 2)
    tier.get("b")  # b freq -> 2
    tier.put("c", 3)  # evict: a freq1 < b freq2 -> a out
    assert "a" not in tier
    assert "b" in tier and "c" in tier


def test_promotion_to_hot_band() -> None:
    tier = LFRUTier(capacity=3, promotion_threshold=3)
    tier.put("x", 1)
    for _ in range(3):
        tier.get("x")
    assert "x" in tier._hot
    assert "x" not in tier._cold


def test_hot_lru_eviction_when_cold_empty() -> None:
    tier = LFRUTier(capacity=2, promotion_threshold=1)
    tier.put("a", 1)  # immediately hot (threshold 1)
    tier.put("b", 2)  # hot
    tier.get("b")  # b most recent
    tier.put("c", 3)  # cold empty -> evict LRU hot = 'a'
    assert "a" not in tier
    assert "b" in tier and "c" in tier


def test_mark_access_unknown_returns_false() -> None:
    tier = LFRUTier(capacity=2)
    assert tier.mark_access("nope") is False
    assert "nope" not in tier


def test_mark_access_promotes() -> None:
    tier = LFRUTier(capacity=3, promotion_threshold=2)
    tier.put("k", 1)
    assert tier.mark_access("k") is True
    assert tier.mark_access("k") is True  # now freq 2 -> hot
    assert "k" in tier._hot


def test_get_returns_value() -> None:
    tier = LFRUTier(capacity=2)
    tier.put("v", {"x": 1})
    assert tier.get("v") == {"x": 1}
    assert tier.get("missing") is None


def test_invalid_capacity() -> None:
    with pytest.raises(ValueError):
        LFRUTier(capacity=0)
    with pytest.raises(ValueError):
        LFRUTier(capacity=2, promotion_threshold=0)
