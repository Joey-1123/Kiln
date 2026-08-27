"""V2 route_trace telemetry (plan A5, colibri ``route_trace.h`` pattern).

A tiny, thread-safe event recorder the engine tiers emit into. Disabled by
default (env ``KILN_ROUTE_TRACE=1``); never imports heavy deps, so it is safe
to construct anywhere in the torch-free zone. Telemetry is what makes future
PILOT-style prefetch a *measurement-dependent* win rather than a guess.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Callable

EventSink = Callable[[dict[str, Any]], None]


class RouteTrace:
    """Collect structured engine events for offline analysis."""

    def __init__(self, enabled: bool | None = None) -> None:
        self._enabled = os.environ.get("KILN_ROUTE_TRACE") == "1" if enabled is None else enabled
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, value: bool) -> None:
        self._enabled = value

    def record(self, event_type: str, **fields: Any) -> None:
        if not self._enabled:
            return
        event = {"event": event_type, **fields}
        with self._lock:
            self._events.append(event)

    def events(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)

    def drain(self) -> list[dict[str, Any]]:
        with self._lock:
            out = list(self._events)
            self._events.clear()
            return out


_default = RouteTrace()


def get_default() -> RouteTrace:
    return _default


def record(event_type: str, **fields: Any) -> None:
    """Emit an event on the process-default recorder (no-op when disabled)."""
    _default.record(event_type, **fields)
