"""Tests for the graph-capturable decode scheduler (plan V2 kernels)."""

from kiln.engine.decode_scheduler import DecodeScheduler


def _inc(state: int) -> int:
    return state + 1


def _double(state: int) -> int:
    return state * 2


def test_run_applies_step_sequence_n_times():
    sched = DecodeScheduler([_inc, _double])
    # one iteration: (s+1)*2
    out = sched.run(3, n_steps=1)
    assert out == (3 + 1) * 2  # 8
    assert sched.step_count == 1


def test_step_count_accumulates():
    sched = DecodeScheduler([_inc])
    sched.run(0, n_steps=5)
    assert sched.step_count == 5


def test_max_steps_guard():
    sched = DecodeScheduler([_inc], max_steps=3)
    try:
        sched.run(0, n_steps=4)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_capture_replays_identical_to_run():
    steps = [_inc, _double]
    sched = DecodeScheduler(steps)
    replay = sched.capture()
    assert sched.captured
    # captured replay must match a non-captured run for identical n_steps
    direct = DecodeScheduler(steps).run(2, n_steps=3)
    captured = sched.run_captured(2, n_steps=3)
    assert direct == captured == replay(replay(replay(2)))


def test_run_captured_requires_capture():
    sched = DecodeScheduler([_inc])
    try:
        sched.run_captured(0, n_steps=1)
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
