"""Tests for utils.ship_verdict — eval gate core."""

from kiln.utils.exitcodes import OK, VERDICT_FAIL
from kiln.utils.ship_verdict import judge, ship_verdict


class TestJudge:
    def test_passes_when_above_threshold(self):
        """Metric above threshold should pass."""
        v = judge(metric_name="accuracy", metric_value=0.95, threshold=0.9)
        assert v.passed is True
        assert v.code == OK

    def test_fails_when_below_threshold(self):
        """Metric below threshold should fail."""
        v = judge(metric_name="accuracy", metric_value=0.85, threshold=0.9)
        assert v.passed is False
        assert v.code == VERDICT_FAIL

    def test_exactly_at_threshold(self):
        """Metric exactly at threshold should pass."""
        v = judge(metric_name="accuracy", metric_value=0.9, threshold=0.9)
        assert v.passed is True

    def test_higher_is_better_false(self):
        """Lower-is-better metric should pass when below threshold."""
        v = judge(
            metric_name="loss",
            metric_value=0.5,
            threshold=1.0,
            higher_is_better=False,
        )
        assert v.passed is True
        assert v.code == OK

    def test_higher_is_better_false_fails(self):
        """Lower-is-better metric should fail when above threshold."""
        v = judge(
            metric_name="loss",
            metric_value=1.5,
            threshold=1.0,
            higher_is_better=False,
        )
        assert v.passed is False
        assert v.code == VERDICT_FAIL

    def test_reason_string(self):
        """Verdict should include a human-readable reason."""
        v = judge(metric_name="acc", metric_value=0.8, threshold=0.9)
        assert "acc" in v.reason
        assert "0.8" in v.reason


class TestShipVerdict:
    def test_all_pass(self):
        """All metrics passing should return OK."""
        v = ship_verdict(
            metrics={"accuracy": 0.95, "f1": 0.92},
            thresholds={"accuracy": 0.9, "f1": 0.9},
        )
        assert v.passed is True
        assert v.code == OK

    def test_one_fails(self):
        """One metric failing should return VERDICT_FAIL."""
        v = ship_verdict(
            metrics={"accuracy": 0.95, "f1": 0.8},
            thresholds={"accuracy": 0.9, "f1": 0.9},
        )
        assert v.passed is False
        assert v.code == VERDICT_FAIL
        assert v.metric_name == "f1"

    def test_missing_threshold(self):
        """Missing threshold for a metric should return USAGE."""
        v = ship_verdict(
            metrics={"accuracy": 0.95, "unknown_metric": 0.5},
            thresholds={"accuracy": 0.9},
        )
        assert v.code == 3  # USAGE
        assert "unknown_metric" in v.reason

    def test_higher_is_better_override(self):
        """Should respect per-metric higher_is_better."""
        v = ship_verdict(
            metrics={"accuracy": 0.95, "loss": 0.3},
            thresholds={"accuracy": 0.9, "loss": 0.5},
            higher_is_better={"accuracy": True, "loss": False},
        )
        assert v.passed is True
        assert v.code == OK

    def test_empty_metrics(self):
        """Empty metrics dict should pass (nothing to fail)."""
        v = ship_verdict(metrics={}, thresholds={})
        assert v.passed is True
