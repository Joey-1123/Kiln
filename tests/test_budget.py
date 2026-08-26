"""Tests for utils.budget — torch-free VRAM preflight."""

import pytest

from kiln.utils.budget import VRAMPreflight, check_vram, estimate_vram_bytes


class TestEstimateVram:
    def test_basic_7b_estimate(self):
        """7B model QLoRA NF4 should estimate ~6-10 GB."""
        est = estimate_vram_bytes(
            param_count=7_000_000_000,
            lora_rank=16,
            lora_target_modules=6,
            batch_size=4,
            seq_len=2048,
            hidden_size=4096,
        )
        # 7B NF4: ~3.5GB weights + grad + optimizer + LoRA + activations
        assert 4_000_000_000 < est < 15_000_000_000

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
