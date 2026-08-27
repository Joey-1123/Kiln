V1 — web dashboard + desktop shell (plan V1 surfaces). `ui/web` is a React + TypeScript
+ Vite dashboard that talks to `kiln serve` (health, models, chat, /v1/metrics).
`ui/desktop` is a Tauri v2 shell that bundles the web build. Both reuse the existing
gateway API; no new backend protocol.
