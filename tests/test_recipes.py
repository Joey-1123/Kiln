"""Tests for the recipe catalog (V1 recipe surface / V2 catalog)."""

from kiln.recipes import get, load_catalog, names


def test_catalog_loads():
    recipes = load_catalog()
    assert {r.name for r in recipes} == {"sft-chat", "dpo-pref", "sft-4bit-stream"}


def test_get_and_fields():
    r = get("sft-4bit-stream")
    assert r.kind == "sft"
    assert r.layer_streaming is True
    assert r.quantization == "4bit"


def test_names_listed():
    assert "dpo-pref" in names()


def test_unknown_raises():
    try:
        get("nope")
        assert False, "expected KeyError"
    except KeyError:
        pass
