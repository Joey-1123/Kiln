"""Tests for V2 route_trace telemetry and its wiring into the LFRU tier (plan A5)."""

from __future__ import annotations

from kiln.engine.cache_tier import LFRUTier
from kiln.engine.route_trace import RouteTrace, get_default, record


def test_disabled_by_default() -> None:
    rt = RouteTrace()
    assert rt.is_enabled() is False
    rt.record("x", k=1)
    assert rt.events() == []


def test_enabled_records_events() -> None:
    rt = RouteTrace(enabled=True)
    rt.record("promote", key="a")
    rt.record("evict", key="b", band="cold")
    assert rt.events() == [
        {"event": "promote", "key": "a"},
        {"event": "evict", "key": "b", "band": "cold"},
    ]


def test_drain_clears() -> None:
    rt = RouteTrace(enabled=True)
    rt.record("e")
    drained = rt.drain()
    assert len(drained) == 1
    assert rt.events() == []


def test_tier_emits_promote_and_evict() -> None:
    rt = RouteTrace(enabled=True)
    tier = LFRUTier(capacity=2, promotion_threshold=2, trace=rt)
    tier.put("a", 1)
    tier.get("a")
    tier.get("a")  # promotes
    tier.put("b", 2)
    tier.put("c", 3)  # evicts
    types = {e["event"] for e in rt.events()}
    assert "lfru_promote" in types
    assert "lfru_evict" in types


def test_module_default_recorder() -> None:
    # default recorder is disabled unless KILN_ROUTE_TRACE=1; ensure no crash.
    record("noop", x=1)
    assert get_default().is_enabled() in (True, False)
