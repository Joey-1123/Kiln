# Kiln — Decision Record

Every decision taken during implementation, with rationale. Locked plan decisions live in
`specs/project-plan.md` §2 (D1–D9) and §13 (amendments A1–A6); this file records
implementation-level decisions made while building.

| # | Date | Decision | Rationale | Status |
|---|------|----------|-----------|--------|
| M1-D1 | 2026-08-26 | Use **uv** to manage the dev virtualenv and pin Python 3.12 for local dev | System python is 3.14 (outside our declared support range ≥3.10,<3.13). uv can fetch managed 3.10–3.12 interpreters; CI matrix still tests all three versions | Accepted |
| M1-D2 | 2026-08-26 | Tracking docs live at repo root: `WORKLOG.md` (what was done), `decision.md` (this file), `COMPLETE.md` (what is completed) | User-requested record keeping; root placement keeps them visible next to README | Accepted |
| M1-D3 | 2026-08-26 | Ruff line length 100, rules `E,F,I,N,W`; no mypy gate in CI yet (lenient later) | Matches Soup conventions; keeps M1 lean. Type hints required on public APIs regardless | Accepted |
| M1-D4 | 2026-08-26 | Exit-code taxonomy as constants module `utils/exitcodes.py`: `0=OK, 1=RUNTIME, 2=VERDICT_FAIL, 3=USAGE` | Soup lesson (v0.71.38): verdict-fail must not share a code with usage errors; pinned by contract test from day 1 | Accepted |
| M1-D5 | 2026-08-26 | All CLI commands defined directly in `cli.py` for M1 (no commands package yet) | Commands are stubs; eager registration in one module makes the startup probe's single import assertion cover the whole surface. Will split into modules when commands grow real bodies | Accepted |
| M1-D6 | 2026-08-26 | Sentinel tests run against source via `PYTHONPATH=src` subprocesses rather than requiring an installed package | Probes must witness the raw import graph; also lets CI run probes before packaging. Editable install still verified separately | Accepted |
| M1-D7 | 2026-08-26 | `[train]` extra pins `transformers>=4.40,<5.0` initially | M1 has no training code yet; will be re-pinned to the version we actually validate the SFT/DPO ladder against in M3 (Soup runs transformers>=5.12) — recorded now so the bump is deliberate | Accepted |
| M1-D8 | 2026-08-26 | CI includes a dedicated `startup-light-probe` job separate from the matrix | A heavy-dep leak should fail loudly on its own, not hide behind unrelated matrix failures | Accepted |
| M1-D9 | 2026-08-26 | Config schema: unknown fields rejected (`extra="forbid"`) from day 1 | Catching typos in kiln.yaml beats silent no-op fields (Soup's "four flags read by nothing" release note); loosening later is easy, tightening after users depend on it is not | Accepted |
| M2-D1 | 2026-08-26 | `huggingface-hub` promoted to core deps, but imported only inside functions | Matches Soup (hub client in light core); keeps the startup probe meaningful — the *heavy* stack remains extras-only | Accepted |
| M2-D2 | 2026-08-26 | HF token stored as plain file at `~/.kiln/token`, chmod 0600 on POSIX; `HF_TOKEN` env takes precedence | No keyring dependency for M2; env precedence matches HF tooling conventions. Windows ACL limitation documented honestly rather than hidden | Accepted |
| M2-D3 | 2026-08-26 | Disk preflight margin = max(5% of model size, 512 MiB); refusal is a runtime error with exact numbers | Covers partial-file overhead and FS overhead; colibri rule — the engine never lies about limits | Accepted |
| M2-D4 | 2026-08-26 | Data lint findings exit **1** (RUNTIME), not 2; malformed input file exits **3** (USAGE) | VERDICT_FAIL stays reserved for eval-gate ship verdicts per the pinned taxonomy; lint problems are dataset defects the user must fix before training | Accepted |
| M2-D5 | 2026-08-26 | Token-count figures use a chars/4 heuristic labeled "~tokens (estimate)" in output | Real tokenizer counts require loading model tokenizers (heavy deps); an honest estimate beats a fake precise number until M3 wires real tokenizers into data tools | Accepted |
| M2-D6 | 2026-08-26 | Ctrl-C exits 130 (conventional shell SIGINT code) outside the 0/1/2/3 taxonomy | Shell convention for signal termination; distinct from all four semantic codes so it can never be confused with them | Accepted |
