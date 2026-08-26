# Milestone 6 — Surfaces (chat TUI, MCP stdio server, env-inventory) + polish

## Features
- Added `kiln chat`: prompt_toolkit REPL with SSE streaming, `/quit /clear /system /history /help` commands, and client mode against a running `kiln serve` (`--server` override)
- Added `kiln mcp serve`: MCP stdio server (mcp SDK 2.x) exposing 6 torch-free tools — `kiln_plan`, `kiln_doctor`, `kiln_fetch`, `kiln_export_gguf`, `kiln_data_lint`, `kiln_data_stats`
- Added `kiln env scan` / `kiln env drift`: pure-AST inventory of `os.environ`/`os.getenv` usage with JSON manifest and drift detection (amendment A6)

## Improvements
- `kiln --version` flag, non-interactive `kiln login --token`, and error output routed to stderr
- README documents shell completions (`source_bash`/`source_zsh`)
- Added docstrings to 78 public symbols across `src/kiln/` (coverage 61% → 98%)
