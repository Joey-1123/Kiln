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

