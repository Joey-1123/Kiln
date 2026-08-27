"""Tests for the V2 decode-only expert-budget guard (plan A8)."""

from __future__ import annotations

import pytest

from kiln.engine.expert_budget import DecodeOnlyError, ExpertBudget


def test_initial_all_active() -> None:
    b = ExpertBudget(total_experts=4)
    assert b.active == {0, 1, 2, 3}
    assert b.phase == "idle"


def test_trim_allowed_in_decode() -> None:
    b = ExpertBudget(total_experts=4)
    b.begin_decode()
    b.trim([0, 1])
    assert b.active == {2, 3}
    b.end()


def test_trim_blocked_in_prefill() -> None:
    b = ExpertBudget(total_experts=4)
    b.begin_prefill()
    with pytest.raises(DecodeOnlyError):
        b.trim([0])
    assert b.active == {0, 1, 2, 3}


def test_trim_blocked_when_idle() -> None:
    b = ExpertBudget(total_experts=4)
    with pytest.raises(DecodeOnlyError):
        b.trim([0])


def test_phase_transitions() -> None:
    b = ExpertBudget(total_experts=2)
    b.begin_prefill()
    assert b.phase == "prefill"
    b.begin_decode()
    assert b.phase == "decode"
    b.end()
    assert b.phase == "idle"


def test_invalid_total_experts() -> None:
    with pytest.raises(ValueError):
        ExpertBudget(total_experts=0)
