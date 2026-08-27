# Kiln — Stub & Implementation Status Tracker

> Reference for future work. Generated 2026-08-27 from `src/kiln/cli.py`,
> `specs/project-plan.md` (v1.3, §8.1 / A1 / A5 / A8 / A9 / A10 / Appendix B),
> and a code scan. Keeping this in sync is a manual step — update it when a
> stub is promoted to implemented and add a `changelog.d` fragment.

Legend: ✅ implemented · ❌ stub / not built · 🔁 deferred to V2/V3

---

## 1. CLI commands (`src/kiln/cli.py`)

| Command | Status | Notes |
|---|---|---|
| `version` | ✅ | prints `kiln.__version__` |
| `login` | ✅ | stores HF token (`hub/auth.py`) |
| `init` | ✅ | writes `kiln.yaml` from a template (chat/train/serve); interactive or `--model`/`--data` for CI |
| `fetch <model>` | ✅ | resumable hub download + disk preflight (`hub/fetch.py`) |
| `data inspect` | ✅ | dataset stats (`data/stats.py`) |
| `data lint` | ✅ | dataset validation |
| `data stats` | ✅ | duplicate/length stats |
| `train` | ✅ | SFT + DPO (`trainer/sft.py`, `trainer/dpo.py`) |
| `serve` | ✅ | API server (`server/`) |
| `doctor` | ✅ | quick/deep, `--json`, mapped exit codes (`doctor/`) |
| `plan` | ✅ | hardware detection → backend/quant recommendation (`plan/`) |
| `chat` | ✅ | prompt_toolkit TUI, streams via `/v1/chat/completions` (`chat/`) |
| `mcp serve` | ✅ | stdio MCP server, read-only + side-effecting tools (`mcp_server/`) |
| `env scan` / `env drift` | ✅ | AST env-var inventory (`env_inventory/`) |
| `export-gguf` | ✅ | HF → quantized GGUF (`export/`) |

**Only remaining code stub:** none — every V1 CLI command is implemented (`_NOT_IMPLEMENTED` is now empty).

---

## 2. V1 surfaces planned but NOT built

| Surface | Plan ref | Status |
|---|---|---|
| React + TS + Vite web dashboard (`web/`) | §5, §6 (line 54, 148) | ❌ not started (no `web/` dir) |
| Tauri v2 desktop shell (`desktop/`, reuses web bundle) | §5, §6 | ❌ not started (no `desktop/` dir) |

Everything else in the V1 surface matrix (CLI, API/OpenAI+Anthropic, TUI, MCP) is built.

---

## 3. Deferred to V2 / V3 (from the plan)

### V2 — 14B everywhere + smarter memory
- **`kiln tune` self-calibration + measurement-cache** — ✅ implemented (A10).
  `src/kiln/tune/` + `tune` CLI; GPU-UUID keyed, OutputDrift TTL guard.
- **LFRU memory tier** — ✅ implemented (A5). `src/kiln/engine/cache_tier.py`
  (cold LFU → hot LRU promotion).
- **route_trace telemetry** — ✅ implemented (A5). `src/kiln/engine/route_trace.py`,
  wired into the LFRU tier; opt-in via `KILN_ROUTE_TRACE=1`.
- **Decode-only expert-budget guard** — ✅ implemented (A8).
  `src/kiln/engine/expert_budget.py` raises `DecodeOnlyError` if trimming is
  attempted outside the decode phase (known prefill-corruption lesson).
- **Custom kernels / batching / expert-banks** behind the existing backend interface;
  must match the transformers oracle **token-for-token at temp 0** (§8, line 96). *Not started.*
- **Full ZMQ 3-process split** (gateway / engine / supervisor) — *deferred* per A1:
  V1 keeps gateway+engine fused in one process over `asyncio.Queue` behind the
  transport seam; split lands only with MoE banks / TP>1 / >~16 concurrent streams.
  Torch-free supervisor already separate.
- **MoE expert offload / hybrid CPU↔GPU banks** — *not started*; adopt the
  offload-cache / cpu-expert-executor model (D7, A9, Appendix B).
- **Layer-streaming** training (opt-in) — training-ladder extension (D5). *Not started.*

### V3 — Big MoE era
- **Big MoE native support**: Qwen3-235B-A3B / GLM-MoE class.
- **Expert offload runtime** (deeper than V2 hybrid).

### Cross-cutting constraints locked for V2+
- **Expert-budget trimming is decode-only only** — the expert-budget rule is
  quarantined (prefill corruption). Any expert-trimming lever must be documented
  decode-only from day 1 (A8).
- **Parity oracle remains the gate** for every new engine/kernels path: logit-window
  tolerance + task-level equivalence (bit-exact cross-engine is impossible) (§8.1, A8).

---

## 4. V2 engine-mining targets (Appendix B — named god nodes to mine)

From the fresh reference graphs:
- LFRU placement tier, route telemetry, auto-tuning.
- Pure-function budget math, offload cache, cpu-expert executor, graph-capturable
  decode.
- Adopt the *pure-function* budget pattern verbatim behind `BackendInfo` (A9).
- **Do NOT copy**: unwired safety gates (A11), reward-hacking subsystem
  (immature).

---

## 5. How to promote a stub

1. Implement the command/module; remove it from `_NOT_IMPLEMENTED` in `cli.py`.
2. Keep heavy deps lazy-imported inside functions (startup-light probe must stay green).
3. Add tests; if it touches inference, wire it into the `parity-oracle` gate where relevant.
4. Add a changelog fragment: `changelog.d/<version>/<slug>.<type>.md`
   (types: feature/fix/docs/perf/breaking).
5. Update this file and `WORKLOG.md`.
