# FINAL PLAN — Kiln (v1.1, name locked)

> Status: **FINAL** — brand = **Kiln**, package = **`kiln-cli`**, CLI = `kiln`.
> Supersedes v1.0. All decisions locked.
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
| D7 | **Inference backends** | **Dual-backend:** CUDA path = native torch+Triton (safetensors, NF4/GPTQ); **CPU path = embedded llama.cpp via llama-cpp-python (GGUF)** behind one capability matrix | bnb-NF4/torchao are CUDA-only/shaky-on-Windows → pure-torch cannot honor D4 honestly; llama.cpp delivers proven CPU tok/s + entire GGUF ecosystem day 1. Matrix seam keeps it swappable. colibri's C engine is a reference for *future* internal improvements, not a direct dependency |
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
│ Gateway: FastAPI — OpenAI (/v1/chat/completions incl. tools) │
│   + Anthropic (/v1/messages) + /health + /v1/models          │
│   + MCP stdio server (generate/chat/status tools)            │
│   Security: localhost bind default · startup API token ·     │
│   MCP execute behind confirmation tokens (Soup pattern)      │
├──────────────────────────────────────────────────────────────┤
│ Engine process (owns device): scheduler · KV cache · sampler │
│   ⇄ ZMQ typed-dataclass messages (FreeToken topology)        │
│   Backend selection = declarative capability matrix          │
│   ├─ cuda: native torch+Triton · paged KV · NF4/GPTQ         │
│   └─ cpu: llama.cpp (llama-cpp-python) · GGUF · mmap threads │
├──────────────────────────────────────────────────────────────┤
│ Trainer (native torch only): sft.py/dpo.py wrappers on       │
│   peft/trl · QLoRA NF4 · lazy heavy imports · eval gate      │
│   run tracker (SQLite) · checkpoint/resume · loss UI feed    │
├──────────────────────────────────────────────────────────────┤
│ Shared: Pydantic config schema (single source of truth) ·    │
│   pure budget-math modules (torch-free) · friendly errors ·  │
│   semantic exit codes · hub fetch/cache manager              │
└──────────────────────────────────────────────────────────────┘
```

Pattern sources: Soup → config discipline, lazy-import probe test, path containment, error mapping, exit codes, security gating. FreeToken → process topology, ZMQ typed messages, capability matrices, budget math. colibri → semantics invariant, oracle CI, doctor/plan/tune triad, generated docs.

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

### V1 — End-to-end loop (≈6 milestones, vertical slices)
1. **Skeleton**: monorepo (src-layout, hatchling, extras `[train][serve][ui][dev]`), config schema v1, CLI shell, UTF-8/path utils, CI matrix (Win/Linux) incl. light-startup probe test.
2. **Fetch & data**: `x fetch <model>` (HF hub, resume, gated-token via `x login`, disk preflight); `x data inspect/lint/preview` (Alpaca/ChatML/ShareGPT auto-detect, val-split).
3. **Train**: SFT then DPO via QLoRA; run tracker + checkpoint resume; eval-gate `x ship` (exit 0/1/2/3); LoRA merge.
4. **Serve**: FastAPI gateway + engine process (ZMQ split); CUDA backend (transformers+NF4); streaming SSE; `/health`; tool-pass-through chat templates.
5. **Serve-anywhere**: llama.cpp CPU backend + GGUF loader/exporter (`x export gguf`); backend auto-selection; `doctor`/`plan`.
6. **Surfaces**: TUI chat; React web chat; Tauri desktop wrapping dist; MCP stdio server; docs site skeleton.

### V2 — 14B everywhere + smarter memory
Layer-streaming opt-in training · CPU↔GPU offload banks · continuous batching + first fused Triton kernels · GPTQ/AWQ menu · elastic VRAM rebalance (`/v1/cache/rebuild`) · dashboard metrics (tok/s, TTFT, memory bars) · recipes catalog · adapter registry w/ lineage · xgrammar-backed JSON-schema/tool-constrained decoding · learned hot-cache (pin hot adapters/KV prefixes).

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

1. Oracle fixtures: tiny random-init checkpoints; **CPU-vs-GPU parity at temp 0** (GGUF path validated by logit-window tolerance + task-level equivalence where bit-exactness doesn't hold across formats — documented honestly per model card).
2. Light-startup probe: heavy deps never load outside training commands.
3. Contract tests: version sync, config round-trip, env-inventory generated from code.
4. Eval gate before ship: task score + regression suites → exit codes.
5. Benchmarks published as-written incl. failures.
6. **GPU CI**: self-hosted runner or cheap spot GPU (runpod/vast.ai) runs the CUDA smoke suite nightly; PR CI covers logic + CPU paths.

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
