# Kiln — Work Log

Running record of what was done, newest at the bottom of each section.

---

## Milestone 1 — Skeleton

### 2026-08-26

- **Session start.** Loaded skills: `python-pro`, `architecture-designer`, `the-fool`, `spec-miner` (earlier sessions). Reference repos cloned to `references/{Soup,colibri,FreeToken}`.
- **Plan finalized to v1.2** (`specs/project-plan.md`) with amendments A1–A6 from the reference-audit comparison.
- **Milestone 1 started** per user go-ahead.

#### M1 implementation
- Created tracking docs: `WORKLOG.md`, `decision.md`, `COMPLETE.md`.
- **Repo scaffold**: `pyproject.toml` (hatchling, `kiln-cli`, src-layout, extras
  `[train][serve][ui][dev]`, light core = typer/rich/pydantic/pyyaml),
  `AGENTS.md`, `.gitignore`, `.pre-commit-config.yaml` (ruff), `changelog.d/` with README.
- **Utils**: `_bootstrap.py` (UTF-8 stdio + Windows codepage 65001),
  `utils/platform.py` (single place for platform branches), `utils/paths.py`
  (realpath+commonpath containment, atomic write, symlink rejection),
  `utils/exitcodes.py` (0/1/2/3 taxonomy), `utils/errors.py`
  (friendly error mapping, KilnError base).
- **Config schema v1** (`config/schema.py`): Pydantic v2 root `KilnConfig` with top-level
  `recipe:` / `eval:` separation, extra=forbid, field validators with clear messages,
  load/save round-trip helpers.
- **CLI shell** (`cli.py`): Typer app, rich console, UTF-8 bootstrap in entry point,
  11 commands registered eagerly (`version` works; 10 stubs exit 1 with notice),
  single mapped exception path → friendly errors → semantic exit codes.
- **Sentinel probes** (`tests/test_cli_startup_is_light.py`,
  `tests/test_supervisor_import_safety.py`): fresh-subprocess sys.modules probe over
  7 heavy deps, control test proving the probe catches a seeded import, light-command
  check, and a meta-path blocker verifying utils/config import with heavy deps unavailable.
- **Contract tests**: version sync (pyproject ↔ `__init__` via hatch source),
  config round-trip identity + unknown-field rejection + clear validator messages,
  exit-code taxonomy pinning, changelog fragment naming.
- **CI**: `.github/workflows/ci.yml` — py3.10/3.11/3.12 × ubuntu/windows matrix +
  dedicated startup-light-probe job; first changelog fragment added.
- **Dev env**: `uv venv --python 3.12 .venv` (system python is 3.14, unsupported).

- **Dev env**: `uv venv --python 3.12 .venv` (system python is 3.14, unsupported).

---

## Milestone 2 — Fetch & Data

### 2026-08-26

#### M2 implementation
- Added `huggingface-hub>=0.30,<2.0` to core deps (Soup pattern: hub client is light-core;
  lazy-imported inside functions so startup probe stays green).
- **`hub/auth.py`**: `kiln login` stores HF token at `~/.kiln/token` (0600 POSIX,
  documented Windows ACL caveat); `HF_TOKEN` env takes precedence; `clear_token` support.
- **`hub/preflight.py`**: disk preflight with injectable `free_space_fn` (tests never touch
  real FS). Safety margin = max(5% model size, 512 MiB). Refuses via `KilnError` with exact
  numbers ("the engine never lies about limits").
- **`hub/fetch.py`**: `probe_model_size()` via `HfApi.model_info(files_metadata=True)`
  (no download); `fetch_model()` = probe → preflight → resumable `snapshot_download`
  into `--dest` (default `./models/<name>`).
- **`data/formats.py`**: row-shape format detection (alpaca/chatml/sharegpt/none),
  majority vote, strict JSONL reader raising with line numbers.
- **`data/lint.py`**: rules with human-facing row numbers — the headline rule is
  `no-loss-target` (empty output / no assistant turn / no gpt turn — guards against
  Soup's "trained on zero tokens" silent failure), plus invalid roles, duplicates,
  unknown-format.
- **`data/stats.py`**: rows/format/duplicates/unrecognized/output-length stats,
  chars-4 token heuristic labeled honestly as an estimate.
- **CLI**: `login`, `fetch`, and `data` sub-app (`inspect` / `lint` / `preview`) wired;
  lint exits 1 on issues, exit 3 on malformed input; graceful Ctrl-C → exit 130.
- Fixed preview branch bug found in smoke test (empty messages list matched ChatML).

---

## Milestone 3 — Train

### 2026-08-26

#### Spike results (§12.2)
- **llama-cpp-python 0.3.35** installed into `.venv` — validates D7/Tier 2 (CPU inference).
- CPU-only path confirmed working: `llama_cpp` imports cleanly, Python 3.12 compatible.
- Spike validates that the GGUF path is viable for V1 CPU serve; full tok/s benchmarks
  deferred to first real model load in M5 (serve milestone).

#### M3 implementation (started)
- **`utils/budget.py`**: torch-free analytic VRAM preflight — pure math, unit-testable
  without CUDA. Estimates QLoRA NF4 memory from model params + sequence length + batch.
- **`config/config_sha.py`**: semantic fingerprint (SHA-256 over recipe-only fields,
  excluding eval/gate policy fields per §12.3). Both raw dict and validated KilnConfig
  produce identical hashes (Pydantic validation injects defaults consistently).
- **`tracking/runs.py`**: SQLite run tracker with WAL mode, race-guarded lazy migrations,
  orphaned-run reconciliation by PID, start/finish/list/get API.
- **`trainer/_compat.py`**: capability probes via `inspect.signature` (never version tables;
  Soup landmine checklist baked in). Probes: sft_config, sft_dataset_text_field,
  dpo_trainer, peft_lora, bnb_4bit.
- **`trainer/sft.py`**: SFT wrapper on peft/trl, QLoRA NF4, landmine checklist (seed before
  `get_peft_model`, construct `SFTConfig` directly, `remove_unused_columns=False`).
- **`trainer/dpo.py`**: DPO wrapper, NaN guard (refuses to save if loss is NaN),
  chosen/rejected validation.
- **`utils/ship_verdict.py`**: eval gate core — judge() for single metric, ship_verdict()
  for multi-metric evaluation. Returns Verdict dataclass with code (0=SHIP, 2=DON'T-SHIP,
  3=USAGE) and human-readable reason.
- **CLI**: `kiln train --config/--mode`, `kiln ship --config/--metric/--value`,
  `kiln merge --adapter/--output/--base-model` wired with proper error handling.
- **Tests**: 46 new tests across 5 test files (budget, config_sha, tracker, ship_verdict,
  compat). All 86 tests pass. Ruff clean. Startup-light probe green.

---

## Milestone 4 — Serve

### 2026-08-26

- **Message protocol** (`engine/messages.py`): typed frozen dataclasses for gateway↔engine
  communication (GenerateRequest, TokenDelta, GenerateComplete, GenerateError, HealthCheck,
  HealthResponse, LoadModelRequest, ModelLoaded). Serialize/deserialize with `__type__`
  discriminator, injection guard (rejects unknown types), numpy-safe codec. Transport seam
  via Protocol (QueueTransport ships as V1 default).
- **Capability matrix** (`engine/backends/__init__.py`): BackendInfo frozen dataclass with
  declarative flags (supports_gpu, supports_nf4, supports_gguf, etc.). Registry with
  register/get/list/select. GPU-preferring auto-selection.
- **CUDA backend** (`engine/backends/cuda_native.py`): CUDABackend with lazy torch imports,
  NF4 quantization via BitsAndBytesConfig, generate + generate_stream.
- **CPU backend** (`engine/backends/llama_cpp.py`): CPUBackend with lazy llama_cpp import,
  GGUF support, generate + generate_stream.
- **Engine loop** (`engine/engine.py`): Engine class dispatching GenerateRequest/HealthCheck/
  LoadModelRequest via transport. Streaming via thread pool executor. Prompt formatting
  (chat messages → prompt string).
- **Gateway** (`engine/gateway.py`): FastAPI app with OpenAI-compatible `/v1/chat/completions`,
  Anthropic-compatible `/v1/messages`, `/v1/models`, `/v1/load`, `/health`. SSE streaming
  with 15s keepalive pings. Auth middleware (X-API-Token). Error envelopes.
- **Supervisor** (`engine/supervisor.py`): Torch-free supervisor, separate process from day 1.
  Ready-ack protocol over stdout. Auto-restart with max_restarts. Signal handling.
- **CLI** (`kiln serve`): `--model/--config/--host/--port/--supervisor`. Single-process fused
  mode (A1 amendment) with engine running alongside gateway. Supervisor mode spawns separate
  engine process.
- **Tests**: 45 new tests across 5 test files (messages, backends, engine, supervisor,
  gateway). All 131 tests pass. Ruff clean. Startup-light probe green.

---

## Milestone 5 — Serve-anywhere

### 2026-08-26

- **M5 implementation.** GGUF export, doctor, plan commands.
- **GGUF export** (`export/__init__.py`): auto-downloads llama.cpp (pinned tag `b5270`) to
  `~/.kiln/llama.cpp/`, builds `llama-quantize` + `convert_hf_to_gguf.py` via cmake. 2-stage
  pipeline: convert HF→f16 GGUF, then quantize to target. Supports Q4_K_M, Q5_K_M, Q8_0, F16.
  Custom `--llama-cpp-dir` override for users who build their own.
- **Doctor** (`doctor/__init__.py`): quick mode (default) checks Python, platform, GPU (nvidia-smi),
  RAM (psutil), disk, 13 dependencies. Deep mode (`--deep`) adds engine binary checks
  (llama.cpp, CUDA backend). Structured JSON via `--json`. Exit code 0=healthy, 1=issues.
- **Plan** (`plan/__init__.py`): detects GPU VRAM, RAM, disk; recommends backend (cuda/cpu) and
  quantization level based on hardware. `--json` for structured output. `--write-config` writes
  suggested backend/quantization to a kiln.yaml file (merges with existing config).
- **CLI**: `export-gguf` replaces the old export stub. `doctor` and `plan` replaced with real
  implementations (--deep/--json/--write-config flags). Removed from `_NOT_IMPLEMENTED`.
- **Tests**: 31 new tests across 3 files (test_export, test_doctor, test_plan). All 162 tests
  pass. Ruff clean. Startup-light probe green.


