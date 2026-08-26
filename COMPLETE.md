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

