# CLI Reference

All commands are available under `kiln`. Run `kiln <command> --help` for the full option list.

## Top-level

| Command | Description |
|---------|-------------|
| `kiln --version` | Print version and exit |
| `kiln version` | Print the Kiln version |
| `kiln init` | Create a new `kiln.yaml` from a template |
| `kiln login [--token]` | Store a Hugging Face token (non-interactive with `--token`) |
| `kiln tune [-f]` | Self-calibrate bandwidth; writes GPU-UUID-keyed cache for `plan` |
| `kiln fetch <model> [-d DIR]` | Download a model from the HF hub (resumable, disk preflight) |
| `kiln train -c <cfg> [-m sft\|dpo]` | Fine-tune a model (QLoRA) |
| `kiln serve [--model] [--port] [--supervisor]` | Start the OpenAI/Anthropic-compatible API server |
| `kiln chat [--server] [--model]` | Interactive TUI chat via a running server |
| `kiln doctor [--deep] [--json]` | GPU / memory / dependency readiness checks |
| `kiln plan [--json] [--write-config PATH]` | Hardware recommendations before downloading |
| `kiln ship -c <cfg> --metric M --value V` | Eval gate; exit code carries the verdict |
| `kiln merge -a <adapter> -o <out> [--base-model]` | Merge LoRA adapter into base model (safetensors) |
| `kiln export-gguf <dir> [-q Q] [-o OUT]` | Export merged model to quantized GGUF |
| `kiln quantize <dir> [-s gptq\|awq] [-c CALIB]` | Quantize into persistent GPTQ/AWQ artifact |
| `kiln recipe-list` | List built-in training recipes |
| `kiln recipe-get <name>` | Show one recipe's fields |

### `kiln init`

```
kiln init [-t chat|train|serve] [-m MODEL] [-d DATA] [-c kiln.yaml] [-f]
```

Interactive by default; pass `--model` / `--data` for non-interactive / CI use.

### `kiln serve`

```
kiln serve [--model MODEL] [--config kiln.yaml] [--host 127.0.0.1] [--port 8000]
           [--supervisor] [--transport queue|zmq]
```

`--supervisor` runs the engine as a child process (`python -m kiln.engine`) over ZMQ, gateway stays in the parent, and a torch-free supervisor monitors the child (READY/ACK, restart on crash). Without it, gateway and engine are fused in one process over `queue`. `--transport zmq` keeps them fused in one process but exercises the ZMQ wire path.

### `kiln chat`

```
kiln chat [--server http://localhost:8080] [--model MODEL]
```

Connects to a running `kiln serve` instance.

## Data subcommands

```
kiln data inspect <file>      # rows, format, lengths, duplicates
kiln data lint <file>         # validate; reports problems with row numbers
kiln data preview <file> [-n N]  # first N rows as formatted chat
```

## MCP

```
kiln mcp serve   # stdio transport; tools: kiln_plan, kiln_doctor, kiln_fetch, ...
```

## Env inventory

```
kiln env scan <path> [-o OUT]          # AST scan for os.environ / os.getenv usage
kiln env drift <manifest> [--path DIR] # diff saved manifest vs current code
```

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | OK / SHIP |
| 1 | Runtime error |
| 2 | Verdict fail (DON'T-SHIP) |
| 3 | Usage error |
| 130 | Interrupted (Ctrl-C) |

Pinned by contract tests in `tests/test_exit_codes.py`.

## Shell completion

```bash
eval "$(_KILN_COMPLETE=source_bash kiln)"
eval "$(_KILN_COMPLETE=source_zsh kiln)"
_KILN_COMPLETE=source_fish kiln | source
```
