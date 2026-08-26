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


