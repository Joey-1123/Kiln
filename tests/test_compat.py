"""Tests for trainer._compat — capability probes."""

import pytest

from kiln.trainer._compat import probe_all, requirecapabilities


class TestProbes:
    def test_probe_all_returns_dict(self):
        """probe_all should return a dict of bools."""
        result = probe_all()
        assert isinstance(result, dict)
        assert len(result) >= 5
        for key in ("sft_config", "sft_dataset_text_field", "dpo_trainer", "peft_lora", "bnb_4bit"):
            assert key in result
            assert isinstance(result[key], bool)

    def test_probe_sft_config(self):
        """SFTConfig probe should return a bool."""
        from kiln.trainer._compat import probe_sft_config_support

        result = probe_sft_config_support()
        assert isinstance(result, bool)

    def test_probe_peft_lora(self):
        """peft lora probe should return a bool."""
        from kiln.trainer._compat import probe_peft_lora

        result = probe_peft_lora()
        assert isinstance(result, bool)


class TestRequireCapabilities:
    def test_passes_when_all_met(self):
        """Should not raise when all capabilities are True."""
        requirecapabilities(sft_config=True, peft_lora=True)

    def test_raises_when_missing(self):
        """Should raise ImportError when any capability is False."""
        with pytest.raises(ImportError, match="Missing required capabilities"):
            requirecapabilities(sft_config=False, peft_lora=True)

    def test_raises_for_multiple_missing(self):
        """Should list all missing capabilities."""
        with pytest.raises(ImportError, match="sft_config"):
            requirecapabilities(sft_config=False, dpo_trainer=False)

    def test_empty_kwargs(self):
        """Empty kwargs should pass without error."""
        requirecapabilities()
