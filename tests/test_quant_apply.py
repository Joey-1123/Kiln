"""Torch-free tests for the quantization application registry (no CUDA needed)."""

from __future__ import annotations

import pytest

from kiln.quant import QUANTIZE_SCHEMES, VALID_NAMES
from kiln.quant.apply import (
    build_quant_spec,
    resolve_load_quant_config,
    resolve_training_quant_config,
)
from kiln.utils.errors import KilnError
from kiln.utils.exitcodes import USAGE


def test_valid_schemes_build_specs() -> None:
    for name in VALID_NAMES:
        spec = build_quant_spec(name)
        assert spec.name == name
        assert spec.bits in (4, 8, 16)


def test_applied_at_tagging() -> None:
    assert build_quant_spec("gptq").applied_at == "artifact"
    assert build_quant_spec("awq").applied_at == "artifact"
    assert build_quant_spec("4bit").applied_at == "train"
    assert build_quant_spec("8bit").applied_at == "train"
    assert build_quant_spec("none").applied_at == "load"


def test_quantize_schemes_subset() -> None:
    assert QUANTIZE_SCHEMES == {"gptq", "awq"}


def test_unknown_scheme_raises_usage() -> None:
    with pytest.raises(KilnError) as exc:
        build_quant_spec("fp8")
    assert exc.value.exit_code == USAGE


def test_load_none_is_identity_without_torch() -> None:
    # "none" must return None without importing torch (keeps control plane light).
    assert resolve_load_quant_config(build_quant_spec("none")) is None


def test_load_gptq_awq_defer_to_artifact_config() -> None:
    # Pre-quantized artifacts carry their own config; load path applies no override.
    assert resolve_load_quant_config(build_quant_spec("gptq")) is None
    assert resolve_load_quant_config(build_quant_spec("awq")) is None


def test_training_rejects_artifact_schemes() -> None:
    for name in ("gptq", "awq"):
        with pytest.raises(KilnError) as exc:
            resolve_training_quant_config(build_quant_spec(name))
        assert exc.value.exit_code == USAGE


def test_training_resolves_bnb_when_torch_present() -> None:
    pytest.importorskip("torch")
    pytest.importorskip("transformers")
    cfg = resolve_training_quant_config(build_quant_spec("4bit"))
    assert cfg is not None
    assert getattr(cfg, "load_in_4bit", False) is True
