# Kiln

> Fine-tune, serve, and chat with open models on consumer hardware — one tool, one config.

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-3c873a?style=flat-square)](https://www.python.org)
[![License](https://img.shields.io/badge/License-Apache--2.0-blue?style=flat-square)](LICENSE)
![Version](https://img.shields.io/badge/version-0.1.0-yellow?style=flat-square)

**Kiln** is a CLI-first local AI workbench that turns a modest machine into a private LLM
studio. One command surface covers the full loop that other tools split apart:

```
data in  →  model trained  →  model served  →  conversation out
```

- **Train** — QLoRA / LoRA / DPO fine-tuning on a consumer GPU
- **Serve** — OpenAI- and Anthropic-compatible APIs; GPU (native torch) or CPU (llama.cpp / GGUF)
- **Chat** — interactive TUI against a running server
- **Private by default** · Apache-2.0 · Linux and Windows first-class

> [!NOTE]
> The chat surface is a TUI today. The web dashboard and desktop shell are on the
> [roadmap](specs/project-plan.md) — see the plan for the full milestone breakdown.

## Features

- **One config file** — `kiln.yaml` drives training, serving, and eval; a content hash pins
  each run for reproducible results.
- **Train on what you have** — QLoRA (NF4) keeps 7–14B models trainable on a single consumer
  GPU; VRAM preflight refuses obviously doomed runs *before* any heavy import.
- **Serve anywhere** — OpenAI `/v1/chat/completions` and Anthropic-compatible endpoints, with a
  CPU backend (llama.cpp + GGUF) for no-GPU machines.
- **Eval gate** — `kiln ship` turns a metric threshold into a SHIP / DON'T-SHIP verdict carried
  by the process exit code, so pipelines can branch on it.
- **MCP server** — expose planning, doctor, fetch, export, and data tooling to MCP clients over
  stdio.
- **Light startup** — heavy dependencies (`torch`, `transformers`, …) are lazy-imported, so the
  CLI and MCP server stay importable without them installed.

## Installation

Kiln needs **Python ≥ 3.10 and < 3.13**. Install from source:

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"        # editable install + test tooling
```

Heavy dependencies are optional extras — install only what you need:

```bash
uv pip install "kiln-cli[train]"  # fine-tuning (torch, transformers, peft, trl, …)
uv pip install "kiln-cli[serve]"  # API server (fastapi, uvicorn, pyzmq)
uv pip install "kiln-cli[all]"    # everything
```

The `kiln` command should now be on your `PATH`. Verify with `kiln --version`.

## Quick start

A minimal end-to-end flow (training requires a CUDA GPU; serving and chat do not):

```bash
# 1. Authenticate for gated models (e.g. Llama 3)
kiln login --token hf_xxx

# 2. Pull a base model (resumable, with a disk-space preflight)
kiln fetch meta-llama/Llama-3.1-8B-Instruct

# 3. Validate a dataset before spending GPU time
kiln data lint data/train.jsonl

# 4. Fine-tune (writes a LoRA adapter)
kiln train -c kiln.yaml -m sft

# 5. Serve an OpenAI-compatible API
kiln serve --model meta-llama/Llama-3.1-8B-Instruct --port 8000

# 6. Chat in the TUI
kiln chat --server http://localhost:8000
```

> [!TIP]
> No GPU? `kiln plan` reports what your machine can serve *before* you download anything, and
> `kiln export-gguf` produces a quantized GGUF you can run on CPU.

## Command reference

| Command | Description |
| --- | --- |
| `kiln login [--token]` | Store a Hugging Face token (non-interactive with `--token`). |
| `kiln fetch <model> [-d DIR]` | Download a model from the HF hub (resumable, disk preflight). |
| `kiln data inspect <file>` | Dataset statistics (rows, format, lengths, duplicates). |
| `kiln data lint <file>` | Validate a dataset; reports problems with row numbers. |
| `kiln data preview <file> [-n N]` | Render the first N rows as formatted chat. |
| `kiln train -c <cfg> [-m sft\|dpo]` | Fine-tune a model (QLoRA). |
| `kiln serve [--model] [--port] [--supervisor]` | Start the OpenAI/Anthropic-compatible API server. |
| `kiln chat [--server] [--model]` | Interactive TUI chat via a running server. |
| `kiln mcp serve` | Start the Kiln MCP server over stdio. |
| `kiln plan [--json] [--write-config PATH]` | Hardware recommendations for serving. |
| `kiln doctor [--deep] [--json]` | GPU / memory / dependency readiness checks. |
| `kiln ship -c <cfg> --metric M --value V` | Eval gate; exit code carries the verdict. |
| `kiln merge -a <adapter> -o <out> [--base-model]` | Merge a LoRA adapter into the base model (safetensors). |
| `kiln export-gguf <dir> [-q Q] [-o OUT]` | Export a merged model to quantized GGUF. |
| `kiln env scan <path> [-o OUT]` | Inventory `os.environ` / `os.getenv` usage (AST). |
| `kiln env drift <manifest> [--path]` | Diff a saved env manifest against the current code. |
| `kiln --version` | Print the version and exit. |

Run `kiln <command> --help` for the full option list on any command.

## Serving example

Once `kiln serve` is running, the endpoint is wire-compatible with the OpenAI SDK:

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "default",
    "messages": [{"role": "user", "content": "Explain QLoRA in one sentence."}]
  }'
```

Interactive API docs are served at `http://localhost:8000/docs`.

> [!IMPORTANT]
> `kiln serve` binds to `127.0.0.1` by default. Expose it on a network interface only on a
> trusted network, and protect it with `--token` if the gateway is configured for auth.

## Configuration

Kiln is driven by a `kiln.yaml` config (Pydantic v2 schema in `src/kiln/config/schema.py`).
The recipe and eval/gate policy are top-level siblings so a semantic config fingerprint can
exclude policy. See [`specs/project-plan.md`](specs/project-plan.md) for the field layout and
the locked design decisions.

```bash
kiln plan --write-config kiln.yaml   # scaffold a serving config from hardware detection
```

## MCP server

`kiln mcp serve` exposes Kiln's tooling to MCP clients over stdio transport, including
`kiln_plan`, `kiln_doctor`, `kiln_fetch`, `kiln_export_gguf`, `kiln_data_lint`, and
`kiln_data_stats`. Heavy dependencies are never imported, so the server starts without a torch
install.

## Development

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
pytest tests/ -v                 # fast suite (smoke tests deselected by default)
ruff check src/kiln/ tests/     # lint — must be clean before any commit
```

The authoritative plan, decisions, and completion records live in `specs/` and the repo's
tracking docs (`WORKLOG.md`, `decision.md`, `COMPLETE.md`).

## Shell completion

`kiln` ships built-in shell completions (Typer/Click). Enable them for your shell:

```bash
# bash
eval "$(_KILN_COMPLETE=source_bash kiln)"

# zsh
eval "$(_KILN_COMPLETE=source_zsh kiln)"

# fish
_KILN_COMPLETE=source_fish kiln | source
```

Add the relevant line to your shell's rc file to persist it.
