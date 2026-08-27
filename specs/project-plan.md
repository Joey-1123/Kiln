# FINAL PLAN — Kiln (v1.3)

> Status: **FINAL** — brand = **Kiln**, package = **`kiln-cli`**, CLI = `kiln`.
> v1.3: merges v1.2 + fresh 2026-08-27 re-read of all three references (Soup + colibri re-cloned & graphified; FreeToken re-added fresh). Amendments A1–A11.
> (`specs/references-analysis.md` + audit reports; see §13).
> Supersedes v1.0/v1.1/v1.2 (merged into one file). All decisions locked; §14 + Appendices A–C add the fresh-reference evidence.
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

---

## 14. Amendments v1.3 (from fresh reference re-reads: Soup · colibri · FreeToken)

| # | Amendment | Rationale (fresh evidence) | Change vs v1.2 |
|---|---|---|---|
| **A7** | FreeToken is a **first-class reference**, on par with Soup + colibri. Document the explicit topology mapping: FreeToken `frontend ⇄ ZMQ ⇄ tokenizer ⇄ scheduler` ⇄ Kiln `gateway ⇄ engine ⇄ torch-free supervisor`, behind our A1 transport seam. | FreeToken freshly re-read (was shallow in v1.2). Its 3-process split is the production shape; it *also* ships an in-process offline mode (`scheduler/io.py`), confirming A1's "V1 doesn't need 3 processes; supervisor covers segfault survivability." | No decision change — adds the mapping so the eventual ZMQ split is a constructor change, not a redesign. |
| **A8** | **Elevate the CPU↔GPU parity oracle to a hard release gate** and lock "expert-budget trimming is decode-only" into the V2 spec. | colibri itself states GPU float matmul ≠ CPU int8 (NOT token-identical; `GPU_BACKENDS.md`). Kiln's V1 runs two *different* engines (native torch vs llama.cpp/GGUF), so cross-backend bit-exactness is impossible — v1.2 already says "logit-window tolerance + task-level equivalence where bit-exactness doesn't hold" but it must be a **CI gate**, not prose. colibri `EXPERT_BUDGET` is quarantined (#292 prefill corruption) → confirms our V2 note. | Strengthens D6 / §8.1: parity oracle becomes a blocking release job; V2 expert-trimming lever documented as decode-only from day 1. |
| **A9** | **V2/V3 engine-mining track gets concrete god-node targets** from the fresh graphs (see Appendix B). Adopt FreeToken's `cache_budget.py` *pure-function* pattern verbatim behind `BackendInfo`. | Fresh god nodes: colibri `Dsv4CudaTensor`/`expert_store`/`tier.h`/`route_trace.h`; FreeToken `OffloadMoeCache` (79), `CpuMoeExecutor` (123), `cache_budget.py` (pure q* math), graph-capturable decode. These are the exact internals to mine for Kiln's V2 offload banks / elastic VRAM. | No decision change — turns the vague "mine colibri" note (§4/V2) into a named, measurable work list. |
| **A10** | Add a **measurement-cache** + `kiln tune` self-calibration spec (FreeToken `benchbw` pattern) to V2. | FreeToken `ft bench bw` writes `$XDG_CACHE_HOME/freetoken/benchbw/<gpu-uuid>.json` and drives prod backend choice (offload vs hybrid). Kiln has `doctor`/`plan` but no bandwidth self-calibration artifact; colibri `autotune.py` is the same idea. | Extends V2 "dashboard metrics / autotune skeleton" into a concrete `tune` subcommand with a GPU-UUID-keyed cache + OutputDrift disqualification (already in §8.7). |
| **A11** | Record a **deliberate divergence**: Kiln's eval gate *enforces*; Soup's safety gates *warn-but-no-op*. | Fresh Soup read: `forgetting_detection` / `checkpoint_intelligence` / `early_stop_on_regression` are accepted but **not enforced** (console warning only, `commands/train.py:709-729`). Kiln's `ship_verdict` is a hard exit-code gate — stricter by design. | No decision change — documents why we do NOT copy Soup's unwired-gate pattern; adds to §9 non-goals rationale. |

### Also adopted from the fresh audit (no decision change)
- FreeToken's **capability matrix validated at config time, not post-load** (`engine/engine.py:158-199`, `test_attention_backend_matrix.py`) — matches our `BackendInfo` registry; keep it pre-load.
- FreeToken's **torch-free daemon + import-sentinel test** (`daemon/__init__.py`, `test_daemon_import_safety.py`) — confirms Kiln's supervisor design (M4-D1/M6 torch-free zone).
- colibri's **format predicate at the device decoder** + **safetensors header cap** — the discipline behind D6; if Kiln ever adds a native quant kernel, copy these refusal patterns.
- FreeToken's **env-key scrubbing when launching agents** (`launch.py`) — adopt *if/when* Kiln adds an agent-launch surface; today its MCP execute-gating (D7/M6-D4) covers the same threat.

---

## Appendix A — 3-reference × Kiln decision comparison matrix

Verdict legend: ✅ confirmed · ⚠️ confirmed-with-caveat · 🔁 refine · ➖ not applicable.

| Kiln v1.2 pattern | Soup (fresh) | colibri (fresh) | FreeToken (fresh) | Verdict |
|---|---|---|---|---|
| D1 Python core + Triton/native kernels | Python/Typer/pydantic; kernels via peft/trl | Pure-C engine, zero deps | Python + Triton + 2 C++ exts | ✅ aligned (Kiln = Python-first like Soup/FreeToken) |
| D2 Dense 7–14B + small MoE; big MoE V3 | 24 tasks, any AutoModelForCausalLM | 744B–2.8T MoE native | 290B+ MoE native (DeepSeek-V4/GLM/...) | ✅ Kiln's staged MoE matches both |
| D5 Soup ladder QLoRA NF4 + peft/trl | SFT/DPO/GRPO/KTO… on peft/trl | n/a (inference) | n/a (inference) | ✅ direct lineage |
| D6 placement/quant changes speed, never tokens | "bit-exact streamed vs resident" claimed (BETA) | invariant, **but GPU float ≠ CPU int8** | parity oracles vs HF reference | ⚠️ keep tolerance gate; not literally bit-exact cross-engine |
| D7 dual-backend (torch + llama.cpp/GGUF) | single torch path | single C engine, multi-tier | offload/offload-hybrid/cpu MoE backends | 🔁 adopt FreeToken's offload/hybrid as V2 CPU↔GPU bank model |
| A1 fused 1-process gateway+engine, ZMQ deferred | MCP server (1 proc) | sentinel stdio engine⇄gateway | 3-proc ZMQ + in-proc offline mode | ✅ A1 validated by FreeToken's own offline mode |
| A2 torch-free message codec | n/a | gateway stdio sentinel framed | msgpack dataclasses, 1D tensors only | ✅ aligned |
| Config single-source-of-truth (schema.py) | `SoupConfig` 6.8k lines | env vars in one `main()` | `ModelConfig` (197 edges, god node) | ✅ Kiln `KilnConfig` mirrors the pattern (lighter) |
| Light/torch-free control plane | lazy-import probe test | stdlib-only `coli` | torch-free daemon + sentinel test | ✅ Kiln supervisor matches |
| Capability matrix / plugin seams | trainer task wrappers | expert-store ops-struct | `BackendInfo` + attention matrix | ✅ Kiln `BackendInfo` confirmed best-practice |
| doctor/plan/tune triad | `soup doctor` | `coli plan/doctor/tune` | `ft bench bw` + `ft daemon` | 🔁 add `kiln tune` (A10) |
| Semantic exit codes + friendly errors | ship 0/1/2/3 + fix cmd | n/a | X-FT-Token control plane | ✅ Kiln taxonomy matches |
| Oracle/measurement CI culture | published benchmarks | transformers oracle, tiny fixtures | HF/vLLM/reference oracles, radix reference model | ✅ adopt as hard gate (A8) |
| Windows first-class | UTF-8 bootstrap, containment | MinGW↔MSVC DLL hygiene | desktop (Tauri) CORS-centric | ✅ Kiln windows-latest CI aligned |

**Net:** Kiln's v1.2 design survives the fresh re-read. Two refinements only: (1) make the parity
oracle a *blocking* CI gate (A8), and (2) add a `tune` self-calibration command + concrete V2/V3
mining targets (A9/A10). No architectural decision is overturned.

---

## Appendix B — V2/V3 engine-mining targets (from fresh god-node graphs)

These are the specific internals to mine, in priority order, behind our `BackendInfo` capability matrix.
Never a fork — always measured end-to-end before adoption (colibri research culture, D6).

**colibri (C engine, reference for tiering/streaming discipline)**
- `tier.h` — LFRU placement math (~100 LOC pure logic; adopt as Python first, C later).
- `route_trace.h` — routing-heat telemetry → `.usage` learning cache (~300 LOC).
- `expert_store.h` / `expert_store_registry.h` — ops-struct plugin seam w/ strict lease contract
  (lookup→release paired; `destroy()` requires zero active leases). Model Kiln's future expert store.
- `st.h` — safetensors index, `O_DIRECT`/`pread`, mirror replicas, `ST_MAX_HEADER` cap.
- `quant.h` — SIMD kernel family (int8/i4/i3/E8/IQ3/MXFP4). Reference if Kiln adds custom quant kernels.
- PILOT router-lookahead prefetch — **LAST** (measurement-dependent, sometimes net-negative per colibri ledger).

**FreeToken (Python/Triton, closest engine shape to Kiln's V2)**
- `engine/cache_budget.py` — **pure-function** q* budget math (MoE-first split, no torch). Adopt verbatim.
- `moe/offload_cache.py` (`OffloadMoeCache`, 79 edges) + `moe/offload_kernels.py` (`ensure_experts`
  LRU slot-cache) — the offload/hybrid CPU↔GPU bank model for Kiln V2.
- `moe/cpu_moe.py` (`CpuMoeExecutor`, 123 edges) — CPU-compute fallback for misses (AVX512-BF16).
- `engine/graph.py` — CUDA-graph-capturable decode (constant-address inputs). V2 "first fused Triton kernels" target.
- `engine/engine.py:_resolve_hybrid_fetch` + `moe/benchbw.py` — bandwidth-adaptive `hybrid_fetch_fraction`
  (the real "q* policy"). Source for Kiln `tune` (A10).
- `kvcache/` radix/ShadowRadix + `dsv4_paged_pool` — prefix-cache + paged KV; reference for Kiln KV rebalance.

**Soup (training/governance — already mined in v1.0/v1.2)**
- Retain: config discipline, lazy-import probe, path containment, error mapping, exit codes, MCP gating.
- **Do NOT copy:** unwired safety gates (A11), reward-hacking subsystem (18 TODOs — immature).

---

## Appendix C — Analysis artifacts

- Fresh deep clones + spec-miner reports: `/home/joey/projects/{Soup,colibri,FreeToken}`
- Knowledge graphs (god nodes, communities, surprising connections):
  - `/home/joey/projects/Soup/graphify-out/graph.html` + `GRAPH_REPORT.md` (33,753 nodes)
  - `/home/joey/projects/colibri/graphify-out/graph.html` + `GRAPH_REPORT.md` (6,547 nodes)
  - `/home/joey/projects/FreeToken/graphify-out/graph.html` + `GRAPH_REPORT.md` (7,994 nodes)
- Kiln is already implemented through Milestone 6 (207 tests passing, `COMPLETE.md`); this v1.3 is a
  **planning** amendment, not a code change. Next action: when V2 starts, open `tier.h`/`cache_budget.py`
  ports and stand up the parity-oracle CI gate from A8.

(End of v1.3 — supersedes v1.2. Sections §1–§13 unchanged; read `specs/project-plan.md`.)
