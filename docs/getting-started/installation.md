# Installation

Kiln needs **Python ≥ 3.10 and < 3.13**.

## From source

```bash
uv venv --python 3.12 .venv
uv pip install -e ".[dev]"
```

Verify:

```bash
kiln --version
kiln --help
```

## Optional extras

Heavy dependencies are isolated in extras — install only what you need:

| Extra | What you get |
|-------|--------------|
| `kiln-cli[train]` | torch, transformers, peft, trl, datasets, accelerate, bitsandbytes, safetensors |
| `kiln-cli[serve]` | fastapi, uvicorn, pyzmq |
| `kiln-cli[quant]` | auto-gptq, autoawq, safetensors |
| `kiln-cli[all]` | train + serve + ui |
| `kiln-cli[docs]` | mkdocs, mkdocs-material |

```bash
uv pip install "kiln-cli[train]"
uv pip install "kiln-cli[serve]"
uv pip install "kiln-cli[all]"
```

Docs tooling:

```bash
uv pip install -e ".[docs]"
mkdocs serve
```

## Shell completion

Typer/Click completions are built in:

```bash
# bash
eval "$(_KILN_COMPLETE=source_bash kiln)"
# zsh
eval "$(_KILN_COMPLETE=source_zsh kiln)"
# fish
_KILN_COMPLETE=source_fish kiln | source
```

Add the line to your shell rc file to persist it.
