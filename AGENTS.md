# Kiln — AGENTS.md

Tool-agnostic entry point for AI coding agents (opencode, Codex, Cursor, Claude Code, etc.).

**Kiln** is a CLI-first local AI workbench: fine-tune → serve → chat with open models on
consumer hardware. Python ≥3.10,<3.13. Apache-2.0.

## Build & test

```bash
uv venv --python 3.12 .venv          # dev interpreter (system python may be unsupported)
uv pip install -e ".[dev]"           # editable install + test deps
pytest tests/ -v                     # fast suite (smoke tests deselected by default)
ruff check src/kiln/ tests/          # lint — must be clean before any commit
```

## Conventions (must follow)

- **Config** is Pydantic v2 in `src/kiln/config/schema.py` — single source of truth.
  Recipe fields and eval/gate policy fields are top-level separated (`recipe:` / `eval:`)
  so semantic config fingerprints can exclude policy without retrofitting.
- **Heavy deps** (`torch`, `transformers`, `peft`, `trl`, `datasets`, `bitsandbytes`,
  `accelerate`) are lazy-imported inside functions, never at module top. Enforced by
  `tests/test_cli_startup_is_light.py` — keep it green.
- **Output** via `rich.console.Console`, never bare `print()`.
- **Path containment**: `os.path.realpath` + `os.path.commonpath` via `utils/paths.py`
  (never `Path.resolve()` + `relative_to()` — breaks on Windows 8.3 short names).
- **Platform differences** go in `utils/platform.py` only — no inline `sys.platform`
  branches elsewhere.
- **Exit codes** come from `utils/exitcodes.py` (`0 OK / 1 RUNTIME / 2 VERDICT_FAIL /
  3 USAGE`) and the taxonomy is pinned by test.
- **Every PR** adds a changelog fragment under `changelog.d/<version>/`; version sync
  between pyproject and `kiln.__version__` is tested.
- Line length 100, ruff rules `E, F, I, N, W`.

## Full plan & records

- Locked plan + milestones: [`specs/project-plan.md`](specs/project-plan.md)
- Reference analysis: [`specs/references-analysis.md`](specs/references-analysis.md)
- Work log / decisions / completion: [`WORKLOG.md`](WORKLOG.md) · [`decision.md`](decision.md) · [`COMPLETE.md`](COMPLETE.md)
