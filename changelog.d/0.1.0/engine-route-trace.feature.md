V2 (A5) — `route_trace` telemetry (`src/kiln/engine/route_trace.py`), the
colibri `route_trace.h` pattern: a thread-safe, opt-in event recorder
(env `KILN_ROUTE_TRACE=1`) the engine tiers emit into. Wired into the LFRU
tier so promotions/evictions are observable — the telemetry that makes future
PILOT-style prefetch a measurement-dependent win rather than a guess.
