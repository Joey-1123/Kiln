"""Tests for the adapter registry (V2)."""

from kiln.trainer.registry import AdapterRegistry


def test_lineage_chain():
    reg = AdapterRegistry(now=lambda: 0.0)
    reg.register("base", base_model="llama-3b")
    reg.register("a", base_model="llama-3b", parent="base")
    reg.register("b", base_model="llama-3b", parent="a")
    chain = reg.lineage("b")
    assert [c.name for c in chain] == ["b", "a", "base"]


def test_parent_must_exist():
    reg = AdapterRegistry()
    try:
        reg.register("x", base_model="m", parent="missing")
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_lineage_cycle_guarded():
    reg = AdapterRegistry(now=lambda: 0.0)
    reg.register("p", base_model="m")
    reg.register("c", base_model="m", parent="p")
    reg._adapters["p"] = reg._adapters["p"].__class__(
        name="p", base_model="m", parent="c", created_at=0.0
    )
    try:
        reg.lineage("c")
        assert False, "expected ValueError"
    except ValueError:
        pass
