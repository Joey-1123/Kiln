"""Tests for utils.budget — torch-free VRAM preflight."""

import pytest

from kiln.utils.budget import (
    ADAM_MOMENT_BYTES_PER_PARAM,
    RUNTIME_WORKSPACE_BYTES,
    VRAMPreflight,
    _vram_budget,
    check_vram,
    estimate_vram_bytes,
)

# Old (pre-correction) flat estimate for 7B@rank16/6/modules/batch4/seq2048 was
# ~3.87 GB because it never priced the trainable-parameter AdamW moments or a
# fixed runtime workspace.  The corrected estimator must land materially above
# that while staying a plausible analytical figure (avoid locking exact GB).
_OLD_7B_ESTIMATE = 4_153_929_753


def _est7(**over):
    """Estimate 7B QLoRA NF4 with representative default settings."""
    kwargs = dict(
        param_count=7_000_000_000,
        lora_rank=16,
        lora_target_modules=6,
        batch_size=4,
        seq_len=2048,
        hidden_size=4096,
        safety_margin_fraction=0.10,
    )
    kwargs.update(over)
    return estimate_vram_bytes(**kwargs)


class TestEstimateVram:
    def test_basic_7b_estimate(self):
        """7B model QLoRA NF4 should estimate several GB, above the old flat figure."""
        est = _est7()
        # Corrected model: base(3.5GB) + trainable + optimizer + activation +
        # runtime(1GB) + 10% margin.  Must be materially above the pre-correction
        # value (which under-priced training-state and runtime costs).
        assert est > _OLD_7B_ESTIMATE * 1.2
        assert 5_000_000_000 < est < 15_000_000_000

    def test_component_breakdown_is_auditable(self):
        """The additive component model must price each cost explicitly."""
        b = _vram_budget(
            param_count=7_000_000_000,
            lora_rank=16,
            lora_target_modules=6,
            batch_size=4,
            seq_len=2048,
            hidden_size=4096,
        )
        assert b["base_bytes"] > 0
        assert b["trainable_bytes"] > 0
        assert b["optimizer_bytes"] > 0
        assert b["activation_bytes"] > 0
        assert b["runtime_bytes"] > 0
        # total == raw peak + margin
        assert b["total"] == b["raw_peak"] + b["margin_bytes"]
        # raw peak is exactly the sum of its components
        assert b["raw_peak"] == (
            b["base_bytes"]
            + b["trainable_bytes"]
            + b["optimizer_bytes"]
            + b["activation_bytes"]
            + b["runtime_bytes"]
        )

    def test_smaller_model_less_memory(self):
        """Smaller model should need less VRAM."""
        small = estimate_vram_bytes(
            param_count=1_000_000_000,
            lora_rank=8,
            lora_target_modules=4,
            batch_size=2,
            seq_len=1024,
            hidden_size=2048,
        )
        big = estimate_vram_bytes(
            param_count=7_000_000_000,
            lora_rank=16,
            lora_target_modules=6,
            batch_size=4,
            seq_len=2048,
            hidden_size=4096,
        )
        assert small < big

    def test_higher_batch_more_memory(self):
        """Larger batch should increase estimate."""
        b1 = estimate_vram_bytes(
            param_count=7_000_000_000,
            lora_rank=16,
            lora_target_modules=6,
            batch_size=2,
            seq_len=2048,
            hidden_size=4096,
        )
        b4 = estimate_vram_bytes(
            param_count=7_000_000_000,
            lora_rank=16,
            lora_target_modules=6,
            batch_size=8,
            seq_len=2048,
            hidden_size=4096,
        )
        assert b1 < b4

    def test_custom_safety_margin(self):
        """Safety margin fraction should affect the result."""
        base = estimate_vram_bytes(
            param_count=7_000_000_000,
            lora_rank=16,
            lora_target_modules=6,
            batch_size=4,
            seq_len=2048,
            hidden_size=4096,
            safety_margin_fraction=0.0,
        )
        with_margin = estimate_vram_bytes(
            param_count=7_000_000_000,
            lora_rank=16,
            lora_target_modules=6,
            batch_size=4,
            seq_len=2048,
            hidden_size=4096,
            safety_margin_fraction=0.20,
        )
        assert with_margin > base


class TestCheckVram:
    def test_fits_when_enough(self):
        """Should report fits=True when VRAM is sufficient."""
        result = check_vram(
            param_count=1_000_000_000,
            lora_rank=8,
            lora_target_modules=4,
            batch_size=2,
            seq_len=1024,
            hidden_size=2048,
            available_vram_bytes=20_000_000_000,
        )
        assert result.fits is True
        assert result.margin_bytes > 0

    def test_doesnt_fit_when_short(self):
        """Should report fits=False when VRAM is insufficient."""
        result = check_vram(
            param_count=7_000_000_000,
            lora_rank=16,
            lora_target_modules=6,
            batch_size=8,
            seq_len=4096,
            hidden_size=4096,
            available_vram_bytes=1_000_000_000,  # 1 GB — way too small
        )
        assert result.fits is False
        assert result.margin_bytes < 0

    def test_properties_return_gb(self):
        """Properties should convert to GB correctly."""
        result = check_vram(
            param_count=1_000_000_000,
            lora_rank=8,
            lora_target_modules=4,
            batch_size=2,
            seq_len=1024,
            hidden_size=2048,
            available_vram_bytes=20_000_000_000,
        )
        assert result.estimated_gb > 0
        assert result.available_gb > 0
        assert isinstance(result.margin_gb, float)

    def test_preflight_result_frozen(self):
        """VRAMPreflight should be a frozen dataclass."""
        result = VRAMPreflight(
            estimated_bytes=1000,
            available_bytes=2000,
            fits=True,
            margin_bytes=1000,
        )
        assert result.fits is True
        assert result.estimated_gb == pytest.approx(1000 / (1024**3))


def _est(p, **over):
    """Estimate a model with ``p`` base params and overridable settings."""
    kwargs = dict(
        lora_rank=16,
        lora_target_modules=6,
        batch_size=4,
        seq_len=2048,
        hidden_size=4096,
        safety_margin_fraction=0.10,
    )
    kwargs.update(over)
    return estimate_vram_bytes(param_count=p, **kwargs)


class TestEstimateScaling:
    """Monotonic memory scaling across model sizes."""

    def test_scales_with_param_count(self):
        values = [_est(p) for p in (1_000_000_000, 3_000_000_000, 7_000_000_000, 13_000_000_000)]
        assert values[0] < values[1] < values[2] < values[3]

    def test_13b_above_7b(self):
        assert _est(13_000_000_000) > _est(7_000_000_000)


class TestOptimizerRegression:
    """The trainable-parameter AdamW term must actually be priced."""

    @pytest.fixture
    def budget(self):
        defaults = dict(
            param_count=7_000_000_000,
            lora_rank=16,
            lora_target_modules=6,
            batch_size=4,
            seq_len=2048,
            hidden_size=4096,
        )

        def _make(**over):
            kwargs = dict(defaults)
            kwargs.update(over)
            return _vram_budget(**kwargs)

        return _make

    def test_optimizer_term_is_positive(self, budget):
        b = budget()
        assert b["optimizer_bytes"] > 0

    def test_optimizer_scales_with_rank(self, budget):
        low = budget(lora_rank=4)
        high = budget(lora_rank=32)
        # More trainable params -> more AdamW moments.
        assert high["optimizer_bytes"] > low["optimizer_bytes"]

    def test_optimizer_priced_on_trainable_not_full_base(self, budget):
        b = budget(lora_rank=8)
        lora_params = 6 * 8 * 4096 * 2
        # Optimizer must equal exactly trainable × 8 B/param — never the whole
        # frozen base (that would over-correct).
        assert b["optimizer_bytes"] == int(lora_params * ADAM_MOMENT_BYTES_PER_PARAM)

    def test_optimizer_prices_large_fraction_of_peak(self, budget):
        b = budget(lora_rank=64, lora_target_modules=48)
        # With a realistic trainable-parameter footprint the optimizer
        # (explicitly absent pre-correction) must be a material line-item,
        # not rounding noise.
        assert b["optimizer_bytes"] > 100 * 1024**2  # > 100 MB
        # AdamW moments are 4× the fp16 weights they track (8 B vs 2 B/param).
        assert b["optimizer_bytes"] == 4 * b["trainable_bytes"]

    def test_optimizer_scales_linearly_with_modules(self, budget):
        small = budget(lora_target_modules=1)
        large = budget(lora_target_modules=4)
        # 4× modules → 4× trainable AdamW moments.
        assert large["optimizer_bytes"] == 4 * small["optimizer_bytes"]


class TestPracticalGuardrails:
    """Corrected estimates must land materially above the old flat numbers."""

    _OLD_13B_ESTIMATE = 6_700_000_000  # pre-correction figure for 13B

    def test_7b_materially_above_old(self):
        assert _est7() > _OLD_7B_ESTIMATE * 1.2

    def test_13b_materially_above_old(self):
        assert _est(13_000_000_000) > self._OLD_13B_ESTIMATE * 1.2

    def test_7b_above_community_floor(self):
        # Community QLoRA-7B figures sit ~8-12 GB; our analytical model must at
        # least clear the pre-correction 3.87 GB by staying above ~5 GB.
        assert _est7() > 5_000_000_000

    def test_runtime_workspace_not_in_margin(self):
        b = _vram_budget(
            param_count=7_000_000_000,
            lora_rank=16,
            lora_target_modules=6,
            batch_size=4,
            seq_len=2048,
            hidden_size=4096,
            safety_margin_fraction=0.0,
        )
        # Runtime is a separate line item, not folded into the generic margin.
        assert b["runtime_bytes"] == RUNTIME_WORKSPACE_BYTES
        assert b["runtime_bytes"] > 0


class TestEstimateStreaming:
    """Streaming must stream only the base term, preserving loss terms."""

    def _stream(self, p, layers=32, **over):
        from kiln.utils.budget import estimate_streaming_vram_bytes

        kwargs = dict(
            lora_rank=16,
            lora_target_modules=6,
            batch_size=4,
            seq_len=2048,
            hidden_size=4096,
            safety_margin_fraction=0.10,
        )
        kwargs.update(over)
        return estimate_streaming_vram_bytes(param_count=p, layers=layers, **kwargs)

    def test_streaming_below_flat(self):
        flat = _est(7_000_000_000)
        streamed = self._stream(7_000_000_000)
        assert streamed < flat

    def test_streaming_preserves_loss_terms(self):
        from kiln.utils.budget import _vram_budget

        b = _vram_budget(
            param_count=7_000_000_000,
            lora_rank=16,
            lora_target_modules=6,
            batch_size=4,
            seq_len=2048,
            hidden_size=4096,
            safety_margin_fraction=0.0,
        )
        fixed = (
            b["trainable_bytes"]
            + b["optimizer_bytes"]
            + b["activation_bytes"]
            + b["runtime_bytes"]
        )
        # Streaming only shrinks base residency; the active/fixed training-state
        # and runtime costs must survive untouched (minus no shared margin here).
        streamed_raw = self._stream(7_000_000_000, safety_margin_fraction=0.0)
        assert streamed_raw >= fixed

    def test_streaming_more_layers_less_peak(self):
        few = self._stream(7_000_000_000, layers=8)
        many = self._stream(7_000_000_000, layers=64)
        assert many < few

    def test_streaming_scales_with_param_count(self):
        values = [self._stream(p) for p in (1_000_000_000, 7_000_000_000, 13_000_000_000)]
        assert values[0] < values[1] < values[2]
