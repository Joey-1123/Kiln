"""Tests for the V3 big-MoE spec + validator."""

from kiln.engine.expert_bank import ExpertBank
from kiln.engine.moe_spec import MoESpec, build_expert_bank, validate_moe_spec


def test_valid_spec_passes():
    validate_moe_spec(MoESpec(num_experts=8, expert_dim=1024, layers=2))


def test_invalid_top_k():
    try:
        validate_moe_spec(MoESpec(num_experts=4, expert_dim=128, top_k=8))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_build_bank_has_all_experts():
    spec = MoESpec(num_experts=4, expert_dim=256, layers=3)
    bank = build_expert_bank(spec, strategy="hybrid")
    assert isinstance(bank, ExpertBank)
    assert len(bank.experts) == 4 * 3
    # registered names follow the l{layer}.e{expert_id} scheme
    assert "l0.e0" in bank.experts and "l2.e3" in bank.experts
