"""Tests for the quantization menu (V2)."""

from kiln.quant import SCHEMES, VALID_NAMES, available, get


def test_menu_has_core_schemes():
    for n in ("none", "4bit", "8bit", "gptq", "awq"):
        assert n in SCHEMES


def test_available_filters_by_backend():
    cuda = available("cuda")
    cpu = available("cpu")
    assert "awq" in cpu and "awq" not in cuda  # AWQ is a GGUF/CPU scheme
    assert "gptq" in cuda and "gptq" not in cpu
    assert "none" in cuda and "none" in cpu  # always valid


def test_get_returns_scheme():
    assert get("4bit").bits == 4
    assert VALID_NAMES == frozenset(SCHEMES)
