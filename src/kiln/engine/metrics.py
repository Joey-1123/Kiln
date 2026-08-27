"""V2 serving metrics — TTFT / tok/s / memory bars (plan V2 dashboard).

A small, torch-free collector the engine/gateway emit into. Per request it records
the wall-clock points needed to derive time-to-first-token (TTFT) and tokens-per-
second, so the dashboard can show honest numbers without touching the heavy path.
A clock is injectable so the math is unit-testable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class RequestMetrics:
    """Accumulated measurements for one request."""

    request_id: str
    started_at: float
    first_token_at: float | None = None
    finished_at: float | None = None
    token_count: int = 0

    @property
    def ttft(self) -> float | None:
        """Time to first token (seconds), or None if no token yet."""
        if self.first_token_at is None:
            return None
        return self.first_token_at - self.started_at

    @property
    def tokens_per_second(self) -> float | None:
        if self.finished_at is None or self.first_token_at is None:
            return None
        span = self.finished_at - self.first_token_at
        if span <= 0:
            return None
        return self.token_count / span


class MetricsCollector:
    """Collects per-request TTFT / tok/s; summarises for the dashboard."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._records: dict[str, RequestMetrics] = {}

    def start(self, request_id: str) -> None:
        self._records[request_id] = RequestMetrics(
            request_id=request_id, started_at=self._clock()
        )

    def first_token(self, request_id: str) -> None:
        rec = self._records.get(request_id)
        if rec is not None and rec.first_token_at is None:
            rec.first_token_at = self._clock()

    def token(self, request_id: str) -> None:
        rec = self._records.get(request_id)
        if rec is not None:
            rec.token_count += 1
            self.first_token(request_id)

    def finish(self, request_id: str) -> None:
        rec = self._records.get(request_id)
        if rec is not None and rec.finished_at is None:
            rec.finished_at = self._clock()

    def snapshot(self) -> list[RequestMetrics]:
        """Return a copy of all recorded metrics (for the dashboard)."""
        return list(self._records.values())

    def get(self, request_id: str) -> RequestMetrics:
        """Return one request's metrics by id."""
        return self._records[request_id]


def summarise(records: list[RequestMetrics]) -> dict[str, float]:
    """Aggregate TTFT / tok/s across finished requests for a dashboard widget."""
    ttfts = [r.ttft for r in records if r.ttft is not None]
    tps = [r.tokens_per_second for r in records if r.tokens_per_second is not None]
    return {
        "avg_ttft": sum(ttfts) / len(ttfts) if ttfts else 0.0,
        "avg_tokens_per_second": sum(tps) / len(tps) if tps else 0.0,
        "requests": float(len(records)),
    }
