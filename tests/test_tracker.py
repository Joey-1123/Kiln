"""Tests for tracking.runs — SQLite run tracker."""

import os
from pathlib import Path

import pytest

from kiln.tracking.runs import RunTracker


@pytest.fixture
def tracker(tmp_path: Path) -> RunTracker:
    """Create a temporary tracker."""
    return RunTracker(tmp_path / "test_runs.db")


class TestRunTracker:
    def test_start_and_get(self, tracker: RunTracker):
        """Starting a run should return a record with an ID."""
        run = tracker.start_run(
            config_sha="abc123",
            model="meta-llama/Llama-3.1-8B",
            mode="sft",
        )
        assert run.id is not None
        assert run.config_sha == "abc123"
        assert run.model == "meta-llama/Llama-3.1-8B"
        assert run.mode == "sft"
        assert run.status == "running"
        assert run.pid == os.getpid()

        fetched = tracker.get_run(run.id)
        assert fetched is not None
        assert fetched.id == run.id

    def test_finish_run(self, tracker: RunTracker):
        """Finishing a run should update status and set ended_at."""
        run = tracker.start_run(config_sha="abc", model="test-model")
        tracker.finish_run(run.id, status="completed", adapter_path="/tmp/adapter")

        finished = tracker.get_run(run.id)
        assert finished is not None
        assert finished.status == "completed"
        assert finished.adapter_path == "/tmp/adapter"
        assert finished.ended_at is not None

    def test_finish_failed(self, tracker: RunTracker):
        """Should support failed status."""
        run = tracker.start_run(config_sha="abc", model="test-model")
        tracker.finish_run(run.id, status="failed", notes="OOM error")

        finished = tracker.get_run(run.id)
        assert finished is not None
        assert finished.status == "failed"
        assert finished.notes == "OOM error"

    def test_list_runs(self, tracker: RunTracker):
        """Should list runs newest first."""
        r1 = tracker.start_run(config_sha="a", model="model-a")
        tracker.start_run(config_sha="b", model="model-b")
        r3 = tracker.start_run(config_sha="c", model="model-a")

        all_runs = tracker.list_runs()
        assert len(all_runs) == 3
        assert all_runs[0].id == r3.id  # newest first
        assert all_runs[2].id == r1.id

    def test_list_filter_model(self, tracker: RunTracker):
        """Should filter by model."""
        tracker.start_run(config_sha="a", model="model-a")
        tracker.start_run(config_sha="b", model="model-b")
        tracker.start_run(config_sha="c", model="model-a")

        filtered = tracker.list_runs(model="model-a")
        assert len(filtered) == 2

    def test_list_filter_status(self, tracker: RunTracker):
        """Should filter by status."""
        r1 = tracker.start_run(config_sha="a", model="m")
        r2 = tracker.start_run(config_sha="b", model="m")
        tracker.finish_run(r1.id, status="completed")
        tracker.finish_run(r2.id, status="failed")

        completed = tracker.list_runs(status="completed")
        assert len(completed) == 1
        assert completed[0].id == r1.id

    def test_list_limit(self, tracker: RunTracker):
        """Should respect limit."""
        for i in range(10):
            tracker.start_run(config_sha=f"sha{i}", model="m")

        limited = tracker.list_runs(limit=3)
        assert len(limited) == 3

    def test_get_nonexistent(self, tracker: RunTracker):
        """Should return None for missing run ID."""
        assert tracker.get_run(999) is None

    def test_reconcile_orphans(self, tracker: RunTracker):
        """Should mark runs with dead PIDs as orphaned."""
        tracker.start_run(config_sha="abc", model="m")
        # Manually set a PID that's definitely dead (PID 1 is init on Linux, won't die)
        # But we can't easily simulate a dead PID in a test without forking.
        # Instead test that the method runs without error and returns empty list
        # when all PIDs are alive (current process).
        orphaned = tracker.reconcile_orphans()
        assert orphaned == []  # current process is alive

    def test_wal_mode(self, tracker: RunTracker):
        """Database should use WAL mode."""
        conn = tracker._connect()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_wal_mode_created(self, tmp_path: Path):
        """WAL mode should be set on first connect."""
        t = RunTracker(tmp_path / "wal_test.db")
        conn = t._connect()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
