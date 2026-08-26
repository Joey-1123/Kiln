# FINAL PLAN — Kiln (v1.2)

> Status: **FINAL** — brand = **Kiln**, package = **`kiln-cli`**, CLI = `kiln`.
> v1.2: amendments A1–A6 from the post-audit comparison of all three references
> (`specs/references-analysis.md` + audit reports; see §13).
> Supersedes v1.0/v1.1. All decisions locked.
> References analyzed: `references/{Soup,colibri,FreeToken}` · findings in `specs/references-analysis.md`
> Engine-internals improvement track: **colibri** is the primary reference for memory-tiering /
> streaming techniques we will borrow in V2/V3 (see §4 note + §11).

---

## 1. Vision

One tool, one config: **fine-tune → serve → chat** with open models on consumer hardware.
GPU optional for everything except full-size training. Windows + Linux first-class.

Positioning claims (each survives contact with reality):
- **Headline:** train AND chat with an 8B model on a 4 GB gaming GPU.
- **Reach:** every supported model chats anywhere — including CPU-only laptops.
- **Gap filled:** nothing polished integrates train→serve→chat under one config
  (Ollama/LM Studio don't train; Soup's serving is secondary).

## 2. Locked decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| D1 | Engine strategy | Python core + Triton/native kernels | Ecosystem reuse; Windows-friendly |
| D2 | Model scope v1 | Dense 7–14B + small MoE (OLMoE-class); big MoE in V3 | Lowest risk; MoE sparsity is a cheap win |
| D3 | UX surfaces | CLI + OpenAI/Anthropic API + Web chat/dashboard + TUI + Tauri desktop | Full surface; web bundle shared |
| D4 | GPU requirement | **Optional** for serve/chat/web/desktop/MCP; required-recommended for training >1B | First-class CPU-only users |
| D5 | Training method | Soup ladder: QLoRA NF4 + peft/trl, SFT+DPO first; layer-streaming opt-in V2 | Proven; honest VRAM floors |
| D6 | Correctness rule | Placement/quant changes speed, never tokens (colibri invariant); CI oracle gates | Trust is the product |
| D7 | **Inference backends** | **Dual-backend:** CUDA path = native torch+Triton (safetensors, NF4/GPTQ); **CPU path = embedded llama.cpp via llama-cpp-python (GGUF)** behind one capability matrix. *A1 (v1.2): V1 gateway+engine fused in one process over asyncio.Queue typed messages with a transport seam; full ZMQ split deferred until MoE banks / TP>1 / high concurrency; torch-free supervisor stays a separate process* | bnb-NF4/torchao are CUDA-only/shaky-on-Windows → pure-torch cannot honor D4 honestly; llama.cpp delivers proven CPU tok/s + entire GGUF ecosystem day 1. Matrix seam keeps it swappable. colibri's C engine is a reference for *future* internal improvements, not a direct dependency |
| D8 | Weight formats | Train/adapters: safetensors (HF). Serve-GPU: safetensors NF4/GPTQ/AWQ. Serve-CPU: GGUF. `x export gguf` bridges both worlds | One converter, no reinvention |
| D9 | License | Apache-2.0 | Matches all three references |

## 3. Hardware support matrix (official targets)

| Tier | Hardware | Models | Expected tok/s | Path |
|---|---|---|---|---|
| 1 | CPU-only, 8 GB RAM | 1–4B dense, OLMoE-class MoE | 20–50 MoE / 15–40 dense | llama.cpp/GGUF |
| 2 | CPU-only, 16 GB RAM | 7–14B Q4 GGUF, 30B-A3B MoE | 5–15 dense / 15–30 MoE | llama.cpp/GGUF |
| 3 | 4–6 GB VRAM GPU | 7–8B train(QLoRA)+chat | 30–120 chat | native torch |
| 4 | 8–24 GB VRAM GPU | 8–14B+ everything | 50–150+ | native torch |

`x doctor` detects the tier; `x plan` shows what a machine can run before downloading anything. The engine never lies about limits (colibri rule).

## 4. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ UX: CLI (Typer) · TUI chat · Web chat+dashboard (React+Vite) │
│     · Tauri v2 desktop shell (same web bundle)               │
├──────────────────────────────────────────────────────────────┤
│ Gateway+Engine: V1 = ONE process, two async halves over      │
│   typed-dataclass messages on asyncio.Queue (A1); message    │
│   codec is numpy-only / torch-free (A2); swapping Queue→ZMQ  │
│   later = constructor change only. API: OpenAI               │
│   (/v1/chat/completions incl. tools) + Anthropic             │
│   (/v1/messages) + /health + /v1/models + MCP stdio server.  │
│   Agent-compat rules (FreeToken lessons): Anthropic streams  │
│   end on message_stop (no [DONE] sentinel), 15s SSE          │
│   keepalive pings, error envelope not FastAPI detail,        │
│   terminal-error-with-code guarantee.                        │
│   Security: localhost bind default · startup API token ·     │
│   MCP execute behind confirmation tokens (Soup pattern)      │
│ Torch-free supervisor stays a SEPARATE process from day 1    │
│   (ready-ack protocol; engine segfault can't kill control).  │
├──────────────────────────────────────────────────────────────┤
│ Engine loop: pull-drain-decode-step (never blocks HTTP)      │
│   Backend selection = declarative capability matrix          │
│   (BackendInfo pure-flag dataclass; registration never       │
│   imports kernels)                                           │
│   ├─ cuda: native torch+Triton · paged KV · NF4/GPTQ         │
│   └─ cpu: llama.cpp (llama-cpp-python) · GGUF · mmap threads │
├──────────────────────────────────────────────────────────────┤
│ Trainer (native torch only): sft.py/dpo.py wrappers on       │
│   peft/trl · QLoRA NF4 · lazy heavy imports · eval gate      │
│   run tracker (SQLite, WAL) · checkpoint/resume · loss feed  │
│   Resume = HF Trainer checkpoint dirs, ORTHOGONAL to the     │
│   tracker (tracker records outcomes; Trainer owns resume).   │
├──────────────────────────────────────────────────────────────┤
│ Shared: Pydantic config schema (single source of truth; CLI  │
│   flags rebuild via model_dump() so validators re-run;       │
│   recipe fields separated from gate/policy fields for        │
│   config_sha) · torch-free budget math · friendly errors ·   │
│   semantic exit codes (pinned by contract test) ·            │
│   hub fetch/cache manager                                    │
└──────────────────────────────────────────────────────────────┘
```

Pattern sources: Soup → config discipline, lazy-import probe test, path containment, error mapping, exit codes, security gating. FreeToken → typed messages, capability matrices, budget math, supervisor/daemon, agent-compat API details. colibri → semantics invariant, oracle CI, doctor/plan/tune triad, generated docs.

### V1 engine note
CUDA runner executes HF `transformers` classes (free OLMoE/Qwen3-MoE support); CPU runner delegates to llama.cpp. Custom kernels/batching/expert-banks arrive V2+ behind the same interface and must match the transformers oracle token-for-token at temp 0.

> **colibri as the engine-improvement reference.** For V2/V3 performance work (CPU↔GPU weight
> offload, expert banks, NVMe tiering, router-predictive prefetch), we will mine `references/colibri`
> directly: its header-shared mechanism libraries (`st.h` storage index, `quant.h` kernels, `tier.h`
> LFRU placement), PILOT prefetch, batch-union I/O, and the **semantics-preserving degradation** invariant
> (placement changes speed, never tokens). These become custom backend internals behind our capability
> matrix — never a fork, always measured end-to-end before adoption, per colibri's research culture.

## 5. Model strategy

| Phase | Models |
|---|---|
| V1 | Llama-3.1-8B, Qwen2.5-7B, Gemma-2/3-9B(+4B), Phi-4-mini, OLMoE-1B-7B |
| V2 | 14B class (Qwen2.5-14B, Phi-4-14B); Qwen3-30B-A3B (Tier 2 showcase) |
| V3 | Big MoE: Qwen3-235B-A3B class, GLM-MoE class; expert offload runtime |

Registry pattern: one package per arch (`models/<arch>/register.py`) + HF arch → module map.

## 6. Roadmap

### V1 — End-to-end loop (6 vertical slices)
1. **Skeleton**: monorepo (src-layout, hatchling, extras `[train][serve][ui][dev]`), config schema v1 (recipe fields separated from gate/policy fields), CLI shell, UTF-8/path utils, CI matrix (Win/Linux) incl. fresh-subprocess light-startup probe test **with control test** (probe must catch a seeded regression — AST/lint guards alone are insufficient, Soup shipped one past them). Exit-code taxonomy pinned by contract test. Changelog fragments + version-sync tests from commit #1.
2. **Fetch & data**: `x fetch <model>` (HF hub, resume, gated-token via `x login`, disk preflight); `x data inspect/lint/preview` (Alpaca/ChatML/ShareGPT auto-detect, val-split).
3. **Train**: SFT then DPO via QLoRA; run tracker (SQLite WAL + race-guarded migrations + orphaned-run reconcile by PID; resume stays HF-Trainer-native, orthogonal to tracker). Training landmine checklist baked in: seed applied *before* `get_peft_model`; construct `SFTConfig` directly (passing `TrainingArguments` silently drops `max_length`); trl compatibility via capability probes (`inspect.signature`), never version tables; DPO memory = 2× batch in VRAM preflight; NaN guard refuses final save; analytic VRAM preflight gate with `--allow-oom-attempt`. Eval-gate `x ship` (exit 0 SHIP / 2 DON'T-SHIP / 3 usage / 1 runtime); semantic config fingerprint (`config_sha`, recipe-only hash excluding gate policy). LoRA merge.
4. **Serve**: FastAPI gateway + engine fused in ONE process as two async halves over typed-dataclass messages on `asyncio.Queue` behind a transport seam (`put()/get()` interface identical for Queue and ZMQ — A1); message codec numpy-only, torch-free (A2); typed-message wire round-trip tests incl. client-dict `__type__` injection guard. CUDA backend (transformers+NF4) selected via BackendInfo capability matrix. Streaming SSE with agent-compat rules (§4). Ready-ack torch-free supervisor as separate process from day 1.
5. **Serve-anywhere**: llama.cpp CPU backend + GGUF loader/exporter (`x export gguf`); backend auto-selection; `doctor`/`plan` (doctor report schema: `{schema_version,status,checks:[{id,status∈pass|fail|warn|skip}],plan}` + mapped exit codes).
6. **Surfaces**: TUI chat; React web chat; Tauri desktop wrapping dist; MCP stdio server; docs site skeleton. Env-inventory generator script scanning `os.environ` sites (A6 — write the automation colibri never did).

### V2 — 14B everywhere + smarter memory
Layer-streaming opt-in training (design adapter save/load with canonical key names from day 1 so this door stays cheap) · CPU↔GPU offload banks · continuous batching + first fused Triton kernels · GPTQ/AWQ menu · elastic VRAM rebalance (`/v1/cache/rebuild`; requires pools designed with rebuild() free-before-alloc + persisted baseline_free/weights_bytes captured at load in V1) · dashboard metrics (tok/s, TTFT, memory bars) · recipes catalog · adapter registry w/ lineage · xgrammar-backed JSON-schema/tool-constrained decoding · learned hot-cache (pin hot adapters/KV prefixes) · **early colibri mining starts cheap here**: tier.h LFRU placement (~100 LOC pure Python) + route_trace telemetry (.usage histogram, ~300 LOC); PILOT-style prefetch LAST (measurement-dependent, sometimes net-negative — always behind the capability matrix, gated by tune-style measurement; optimize cold-miss recall, not routing recall). Any expert-budget trimming lever is decode-only (colibri #292 prefill corruption).

### V3 — Big MoE era
Expert banks + device-side LRU + bandwidth-adaptive q\* CPU/GPU split · optional NVMe tier cache plugin · big-MoE targets · MoE LoRA training · opportunistic multi-GPU inference · tool-call anchor checkpoints for agent reuse.

## 7. Repo layout

```
pyproject.toml · AGENTS.md · LICENSE(Apache-2.0)
src/kiln/
  cli.py                  # Typer app, semantic exits, friendly errors
  config/schema.py        # Pydantic single source of truth
  trainer/{sft,dpo,_compat}.py    # lazy heavy imports inside functions
  engine/{scheduler,zmq,kv,sample}/
  engine/backends/{cuda_native,llama_cpp}.py  # capability matrix
  models/{llama,qwen,gemma,phi,olmoe}/register.py
  server/{openai_api,anthropic_api,mcp}.py
  hub/{fetch,cache}.py    # download/resume/gated-token/preflight
  data/{formats,inspect,lint}.py
  tracking/runs.py        # SQLite run history
  utils/{paths,errors,detect,budget}.py   # budget = pure torch-free math
tests/                    # startup-light probe · cpu-gpu parity oracle · contracts
web/ (React+TS+Vite)  desktop/ (Tauri v2)  docs/  benchmarks/  specs/
```

## 8. Correctness & testing

1. Oracle fixtures: tiny random-init checkpoints; **CPU-vs-GPU parity at temp 0** (GGUF path validated by logit-window tolerance + task-level equivalence where bit-exactness doesn't hold across formats — documented honestly per model card). Oracle runs at cache capacities {1, 2, 8} (eviction-on-every-expert is where placement bugs hide — colibri practice). Fixture *generation* (pinned torch, CI-only job) strictly separated from fixture *consumption* (torch-free pure-Python compare); fixtures regenerated in CI or the gate silently rots. Don't gate token-exactness under profilers/differing Triton autotune configs — pin them.
2. Light-startup probe: fresh-subprocess `sys.modules` assertion + control test proving the probe catches a seeded regression; heavy deps never load outside training commands. Second import-sentinel probe for the torch-free supervisor package.
3. Contract tests: version sync, config round-trip, env-inventory generated from code by a real script (A6), exit-code taxonomy, typed-message wire round-trips.
4. Eval gate before ship: task score + regression suites → exit codes; evidence stamped with `{kiln_version, scorer_revision}` and `config_sha`; stale/mismatched evidence refuses to validate.
5. Benchmarks published as-written incl. failures; rejected optimizations recorded with measurements (colibri ledger culture).
6. **GPU CI**: self-hosted runner or cheap spot GPU (runpod/vast.ai) runs the CUDA smoke suite nightly; PR CI covers logic + CPU paths.
7. Autotune/tuning skeleton borrowed from colibri when tuning arrives: tunable-key whitelist ∩ capability matrix, OutputDrift disqualification (any candidate that changes output tokens vs baseline is disqualified), safety gates, reverse-order confirmation, machine-fingerprint profiles with load-time re-admission.

## 9. Explicit non-goals (V1–V3)

Multimodal/vision/audio · cloud/training orchestration · multi-user teams/auth servers · plugin marketplace · fine-tuning on CPU beyond tiny test models · frontier-model disk-tiering claims (until V3 makes them real).

## 10. Risks

| Risk | Mitigation |
|---|---|
| Dual-format maintenance (safetensors+GGUF) drift | Single conversion utility + parity tests per release; adapters always safetensors |
| llama-cpp-python build pain on Windows | Pin prebuilt wheels; fallback documented; isolated in backend module |
| Scope creep across 5 surfaces | Milestone gates; non-goals §9; every feature eval-gated |
| Windows quirks | Soup bootstrap/containment utilities from commit #1; windows-latest CI |
| CPU perf vs Ollama expectations | llama.cpp core means we inherit its numbers; publish tier matrix instead of marketing hype |

## 11. Naming (LOCKED)

- **Brand:** Kiln — where raw clay becomes pottery; you *fire* a raw model into a usable one.
- **Package:** `kiln-cli` (PyPI convention like `soup-cli`; base `kiln` is taken).
- **CLI verb:** `kiln` → `kiln init · train · serve · chat · doctor`.
- Rejected candidates considered: Hearth, Whetstone, Still, Wren, Ember, Grist (all PyPI-occupied).

## 12. Bootstrap checklist (next actions)

1. Create repo, LICENSE(Apache-2.0), AGENTS.md, `pyproject.toml` as `kiln-cli`, src-layout `src/kiln/` (Milestone 1).
2. Spike (≤1 day): llama-cpp-python install on this Windows box + load a Q4 7B GGUF + measure tok/s → validates D7/Tier 2 before anything else is built on top.
3. Scaffold config schema (`config/schema.py`) + CLI shell (`cli.py`) + CI matrix (Win/Linux).
4. Keep `references/{Soup,colibri,FreeToken}` checked out for pattern lookup during implementation.

---

## 13. Amendments v1.2 (from post-audit comparison vs all three references)

| # | Amendment | Rationale (evidence) |
|---|---|---|
| A1 | V1 gateway+engine fused in ONE process: two async halves over typed-dataclass messages on `asyncio.Queue` behind a transport seam; full ZMQ split deferred until MoE banks / TP>1 / >~16 concurrent streams; torch-free supervisor stays a separate process from day 1 | FreeToken itself ships an in-process offline mode (`scheduler/io.py`); 3-process split buys GIL/crash isolation that V1 doesn't need — supervisor already covers segfault survivability |
| A2 | Message codec is numpy-only / torch-free; decide before freezing the message module | FreeToken's gateway accidentally imports torch via `message.utils` — coupling they can't undo |
| A3 | Training landmine checklist baked into trainer design (seed before `get_peft_model`; construct `SFTConfig` directly; capability probes not version tables; DPO = 2× batch in VRAM preflight; NaN guard refuses final save) | Soup's sft.py/dpo.py bug history (#78, #353, #359); each cost a silent failure or wasted run |
| A4 | Exit-code taxonomy pinned by contract test (0 SHIP / 2 DON'T-SHIP / 3 usage / 1 runtime); checkpoint resume stays HF-Trainer-native, orthogonal to the SQLite tracker (tracker: WAL + race-guarded migrations + orphan reconcile by PID) | Soup merged regression-fail with usage-error on exit 2 until v0.71.38; tracker/resume coupling was never Soup's design |
| A5 | V2 colibri mining starts cheap & early: tier.h LFRU (~100 LOC pure Python) + route_trace telemetry (~300 LOC) adoptable incrementally; PILOT-style prefetch LAST and always behind the capability matrix (measurement-dependent win, sometimes net-negative); any expert-budget trimming is decode-only | colibri `tier.h`, `route_trace.h`, PILOT ledger docs, issue #292 prefill corruption |
| A6 | Write the real env-inventory generator script colibri never automated (theirs is a manual/AI-assisted procedure despite "Generated" header); CI drift check | colibri `docs/MAINTAINING-DOCS.md`; scanning Python getenv sites is trivial by comparison |

Also adopted from the audit (no decision change required): agent-compat API rules into §4 (Anthropic no-[DONE] sentinel, SSE keepalive pings, error envelope override, terminal-error-with-code guarantee, system-message hoisting, count_tokens off hot path); BackendInfo pure-flag capability registry pattern; ready-ack supervisor protocol; config fingerprint/provenance stamping; oracle multi-capacity gating; changelog fragments + version-sync tests from commit #1.
