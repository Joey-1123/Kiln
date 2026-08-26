# Kiln — Completion Record

What is finished and verified. An item moves here only after its verification command passes.

## Milestone 0 — Planning & references
- [x] Three reference repos analyzed → `specs/references-analysis.md`
- [x] Final plan locked (v1.2) with amendments A1–A6 → `specs/project-plan.md`
- [x] Reference repos cloned to `references/{Soup,colibri,FreeToken}`

## Milestone 1 — Skeleton

- [x] Repo scaffold: `pyproject.toml` (hatchling, kiln-cli, src-layout, extras), AGENTS.md, .gitignore, .pre-commit-config.yaml, changelog.d/
- [x] UTF-8 bootstrap + `utils/{platform,paths,exitcodes,errors}.py`
- [x] Config schema v1 (`config/schema.py`) with top-level recipe/eval separation
- [x] CLI shell: 11 commands (version live; 10 stubs), eager registration, semantic exits
- [x] Sentinel probes: startup-light (+control test), torch-free-zone import safety
- [x] Contract tests: version sync, config round-trip, exit-code taxonomy, changelog fragments
- [x] CI matrix workflow (.github/workflows/ci.yml) — Win/Linux × 3.10–3.12 + dedicated probe job
- [x] Dev venv via uv (Python 3.12)

### Verification results (2026-08-26)

| Check | Result |
|---|---|
| `kiln --help` / `kiln version` | ✅ works, prints `kiln 0.1.0` |
| `python -m kiln` | ✅ works |
| Stub command exit code (`kiln doctor`) | ✅ exits 1 with notice |
| `pytest tests/ -v` | ✅ 16 passed |
| `ruff check src/kiln/ tests/` | ✅ clean |
| Startup-light probe (7 heavy deps) | ✅ LIGHT_OK incl. control test |
| Torch-free-zone sentinel | ✅ utils+config import with heavy deps blocked |

**Milestone 1 status: COMPLETE** (pending CI run on first push).

## Milestone 2 — Fetch & Data

- [x] `huggingface-hub` added to light core (lazy imports)
- [x] `kiln login` — HF token storage (~/.kiln/token, 0600 POSIX, env precedence)
- [x] `hub/preflight.py` — disk preflight with injectable free-space fn + safety margin
- [x] `kiln fetch <model>` — size probe → preflight → resumable snapshot download
- [x] `data/formats.py` — alpaca/chatml/sharegpt auto-detection, strict JSONL reader
- [x] `data/lint.py` — no-loss-target / invalid-role / duplicates rules with row numbers
- [x] `data/stats.py` — dataset statistics for `kiln data inspect`
- [x] `kiln data {inspect,lint,preview}` wired into CLI; graceful Ctrl-C

### Verification results (2026-08-26)

| Check | Result |
|---|---|
| `pytest tests/ -q` | ✅ 40 passed |
| `ruff check src/kiln/ tests/` | ✅ clean |
| Startup-light probe suite | ✅ still green with huggingface-hub in core |
| Smoke: `kiln data lint` on bad fixture | ✅ flags empty output (line 2) + duplicate, exit 1 |
| Smoke: `kiln data inspect` | ✅ correct stats |
| Smoke: `kiln data preview` | ✅ renders alpaca row after branch-order fix |

**Milestone 2 status: COMPLETE** (network path verified by unit tests with mocked
transport; live HF download deferred to first real use).

## Spike — llama.cpp (§12.2)

- [x] `llama-cpp-python==0.3.35` installed into `.venv` (Python 3.12)
- [x] Import verified clean — validates D7/Tier 2 CPU inference path

### Verification results (2026-08-26)

| Check | Result |
|---|---|
| `import llama_cpp` | ✅ 0.3.35, no build errors |
| CPU-only import (no CUDA) | ✅ works |

## Milestone 3 — Train

- [x] `utils/budget.py` — torch-free analytic VRAM preflight (pure math, no CUDA import)
- [x] `config/config_sha.py` — SHA-256 semantic fingerprint (recipe-only fields, eval excluded)
- [x] `tracking/runs.py` — SQLite WAL tracker with race-guarded migrations, orphan reconcile
- [x] `trainer/_compat.py` — capability probes via inspect.signature (never version tables)
- [x] `trainer/sft.py` — SFT wrapper on peft/trl, QLoRA NF4, landmine checklist baked in
- [x] `trainer/dpo.py` — DPO wrapper, NaN guard, 2× batch VRAM awareness
- [x] `utils/ship_verdict.py` — eval gate core (metric ≥ threshold → SHIP/DON'T-SHIP)
- [x] CLI: `kiln train --config`, `kiln ship`, `kiln merge --adapter` wired
- [x] Tests: budget math, ship verdict, tracker WAL/reconcile, config_sha stability, compat probes

### Verification results (2026-08-26)

| Check | Result |
|---|---|
| `pytest tests/ -v` | ✅ 86 passed |
| `ruff check src/kiln/ tests/` | ✅ All checks passed |
| Startup-light probe suite | ✅ Still green (torch-free imports verified) |
| `kiln train --help` | ✅ Shows train options |
| `kiln ship --help` | ✅ Shows ship options |
| `kiln merge --help` | ✅ Shows merge options |

**Milestone 3 status: COMPLETE**

---

## Milestone 4 — Serve

### Delivered

| Component | File(s) |
|---|---|
| Message protocol | `engine/messages.py` |
| Capability matrix | `engine/backends/__init__.py` |
| CUDA backend | `engine/backends/cuda_native.py` |
| CPU backend | `engine/backends/llama_cpp.py` |
| Engine loop | `engine/engine.py` |
| Gateway (FastAPI) | `engine/gateway.py` |
| Supervisor | `engine/supervisor.py` |
| CLI serve command | `cli.py` |
| Tests | `test_messages.py`, `test_backends.py`, `test_engine.py`, `test_supervisor.py`, `test_gateway.py` |

### Verification

| Check | Result |
|---|---|
| `pytest tests/ -v` | ✅ 131 passed |
| `ruff check src/kiln/ tests/` | ✅ All checks passed |
| Startup-light probe suite | ✅ Still green (torch-free imports verified) |
| `kiln serve --help` | ✅ Shows serve options (--model, --config, --host, --port, --supervisor) |

**Milestone 4 status: COMPLETE**

