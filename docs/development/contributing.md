# Contributing

## Build & test

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
pytest tests/ -v
ruff check src/kiln/ tests/
```

Heavy deps (`torch`, `transformers`, `peft`, `trl`, `datasets`, `bitsandbytes`, `accelerate`) are lazy-imported inside functions, never at module top. Enforced by `tests/test_cli_startup_is_light.py`.

## Conventions

- **Config** is Pydantic v2 in `src/kiln/config/schema.py` — single source of truth.
- **Output** via `rich.console.Console`, never bare `print()`.
- **Path containment**: `os.path.realpath` + `os.path.commonpath` via `utils/paths.py`.
- **Platform differences** go in `utils/platform.py` only.
- **Exit codes** from `utils/exitcodes.py` (0 OK / 1 RUNTIME / 2 VERDICT_FAIL / 3 USAGE).
- Every PR adds a changelog fragment under `changelog.d/<version>/`.
- Line length 100, ruff rules `E, F, I, N, W`.

## Docs

```bash
uv pip install -e ".[docs]"
mkdocs serve      # http://127.0.0.1:8000
mkdocs build --strict
```

Deployed to GitHub Pages on push to `master` via `.github/workflows/docs.yml`.

## Benchmarks

See [Benchmarks](benchmarks.md).

## Changelog

`changelog.d/<version>/` — one fragment per PR. Version sync between `pyproject.toml` and `kiln.__version__` is tested.
