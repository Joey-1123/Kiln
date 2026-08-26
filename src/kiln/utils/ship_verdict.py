"""Eval-gate core: metric ≥ threshold → SHIP / DON'T-SHIP.

Exit codes:
  0 = SHIP (metric passes threshold)
  2 = DON'T-SHIP (metric below threshold)
  3 = USAGE (bad config / missing evidence)

The verdict function is pure logic — no I/O — so it's easy to test.
Evidence stamping (config_sha, kiln_version) happens at the caller.
"""

from __future__ import annotations

from dataclasses import dataclass

from kiln.utils.exitcodes import OK, USAGE, VERDICT_FAIL


@dataclass(frozen=True)
class Verdict:
    """Result of an eval gate check."""

    code: int  # OK (0) or VERDICT_FAIL (2)
    metric_name: str
    metric_value: float
    threshold: float
    passed: bool
    reason: str

    @property
    def is_ship(self) -> bool:
        """True when the measured metric meets the ship threshold."""
        return self.code == OK


def judge(
    *,
    metric_name: str,
    metric_value: float,
    threshold: float,
    higher_is_better: bool = True,
) -> Verdict:
    """Evaluate a single metric against a threshold.

    Parameters
    ----------
    metric_name : str
        Human-readable metric name (e.g. "accuracy", "win_rate").
    metric_value : float
        The measured value.
    threshold : float
        The minimum acceptable value.
    higher_is_better : bool
        If True, metric must be >= threshold.  If False, metric must be <= threshold.
    """
    if higher_is_better:
        passed = metric_value >= threshold
        direction = ">="
    else:
        passed = metric_value <= threshold
        direction = "<="

    if passed:
        return Verdict(
            code=OK,
            metric_name=metric_name,
            metric_value=metric_value,
            threshold=threshold,
            passed=True,
            reason=f"{metric_name}={metric_value:.4f} {direction} {threshold:.4f}",
        )
    return Verdict(
        code=VERDICT_FAIL,
        metric_name=metric_name,
        metric_value=metric_value,
        threshold=threshold,
        passed=False,
        reason=(
            f"{metric_name}={metric_value:.4f} did not meet "
            f"threshold {direction} {threshold:.4f}"
        ),
    )


def ship_verdict(
    metrics: dict[str, float],
    thresholds: dict[str, float],
    higher_is_better: dict[str, bool] | None = None,
) -> Verdict:
    """Evaluate all metrics; any failure means DON'T-SHIP.

    Returns the first failing verdict, or the OK verdict from the first
    metric if all pass.
    """
    higher = higher_is_better or {}
    if not metrics:
        return Verdict(
            code=OK,
            metric_name="",
            metric_value=0.0,
            threshold=0.0,
            passed=True,
            reason="No metrics to evaluate",
        )
    for name, value in metrics.items():
        thr = thresholds.get(name)
        if thr is None:
            return Verdict(
                code=USAGE,
                metric_name=name,
                metric_value=value,
                threshold=0.0,
                passed=False,
                reason=f"No threshold defined for metric '{name}'",
            )
        v = judge(
            metric_name=name,
            metric_value=value,
            threshold=thr,
            higher_is_better=higher.get(name, True),
        )
        if not v.passed:
            return v
    # All passed — return OK verdict summarising
    first_name = next(iter(metrics))
    return Verdict(
        code=OK,
        metric_name=first_name,
        metric_value=metrics[first_name],
        threshold=thresholds[first_name],
        passed=True,
        reason="All metrics passed",
    )
