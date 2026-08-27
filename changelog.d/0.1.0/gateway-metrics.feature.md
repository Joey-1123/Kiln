V2 — gateway serving metrics (`src/kiln/engine/gateway.py`). The gateway now holds a
`MetricsCollector` and emits per-request TTFT / token counts for streaming and
non-streaming OpenAI + Anthropic paths. New `GET /v1/metrics` returns the
aggregated summary for the dashboard.
