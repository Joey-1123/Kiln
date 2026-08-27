"""Tests for continuous batching (V2)."""

from kiln.engine.batching import ContinuousBatcher


def test_admits_up_to_max_batch():
    b = ContinuousBatcher(max_batch=2)
    b.submit("r1")
    b.submit("r2")
    b.submit("r3")
    assert b.step() == ["r1", "r2"]
    assert b.pending == 3  # r3 still waiting


def test_completes_frees_room_for_waiting():
    b = ContinuousBatcher(max_batch=2)
    b.submit("r1")
    b.submit("r2")
    b.submit("r3")
    b.step()
    b.complete("r1")
    assert b.step() == ["r2", "r3"]


def test_max_batch_at_least_one():
    try:
        ContinuousBatcher(max_batch=0)
        assert False, "expected ValueError"
    except ValueError:
        pass
