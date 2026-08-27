"""Capability probes via inspect.signature — never version tables.

Checking transformers.__version__ to decide API shape
breaks silently when upstream changes internals.  Instead we probe
the actual constructor signature at runtime.

Each probe returns True/False indicating whether the installed library
supports the feature we need.
"""

from __future__ import annotations

import inspect
import logging

log = logging.getLogger(__name__)


def probe_sft_config_support() -> bool:
    """Check if trl has SFTConfig (vs only TrainingArguments).

    TRL <0.7 used TrainingArguments for SFT; SFTConfig was added in 0.7+.
    We require SFTConfig to avoid the silent max_length drop bug.
    """
    try:
        from trl import SFTConfig  # noqa: F401

        return True
    except ImportError:
        return False


def probe_sft_dataset_text_field() -> bool:
    """Check if SFTTrainer accepts dataset_text_field parameter."""
    try:
        from trl import SFTTrainer

        sig = inspect.signature(SFTTrainer.__init__)
        return "dataset_text_field" in sig.parameters
    except (ImportError, ValueError):
        return False


def probe_dpo_trainer() -> bool:
    """Check if trl has DPOTrainer."""
    try:
        from trl import DPOTrainer  # noqa: F401

        return True
    except ImportError:
        return False


def probe_peft_lora() -> bool:
    """Check if peft has get_peft_model + LoraConfig."""
    try:
        from peft import LoraConfig, get_peft_model  # noqa: F401

        return True
    except ImportError:
        return False


def probe_bnb_4bit() -> bool:
    """Check if bitsandbytes 4-bit quantization is available."""
    try:
        from transformers import BitsAndBytesConfig

        cfg = BitsAndBytesConfig(load_in_4bit=True)
        return cfg.load_in_4bit is True  # type: ignore[return-value]
    except (ImportError, TypeError):
        return False


def probe_gptq() -> bool:
    """Check if transformers can consume a GPTQ-quantized model (GPTQConfig)."""
    try:
        from transformers import GPTQConfig  # noqa: F401

        return True
    except ImportError:
        return False


def probe_awq() -> bool:
    """Check if transformers can consume an AWQ-quantized model (AwqConfig)."""
    try:
        from transformers import AwqConfig  # noqa: F401

        return True
    except ImportError:
        return False


def probe_auto_gptq() -> bool:
    """Check if the auto-gptq GPTQ training library is installed."""
    try:
        import auto_gptq  # noqa: F401

        return True
    except ImportError:
        return False


def probe_auto_awq() -> bool:
    """Check if the auto-awq AWQ training library is installed."""
    try:
        import awq  # noqa: F401

        return True
    except ImportError:
        return False


def probe_all() -> dict[str, bool]:
    """Run all probes and return a capability dict."""
    results = {
        "sft_config": probe_sft_config_support(),
        "sft_dataset_text_field": probe_sft_dataset_text_field(),
        "dpo_trainer": probe_dpo_trainer(),
        "peft_lora": probe_peft_lora(),
        "bnb_4bit": probe_bnb_4bit(),
        "gptq": probe_gptq(),
        "awq": probe_awq(),
        "auto_gptq": probe_auto_gptq(),
        "auto_awq": probe_auto_awq(),
    }
    log.debug("capability probes: %s", results)
    return results


def requirecapabilities(**caps: bool) -> None:
    """Raise if any capability is missing.

    Usage::

        requirecapabilities(sft_config=True, peft_lora=True)
    """
    missing = [k for k, v in caps.items() if not v]
    if missing:
        raise ImportError(
            f"Missing required capabilities: {', '.join(missing)}. "
            'Install training deps: pip install "kiln-cli[train]"'
        )
