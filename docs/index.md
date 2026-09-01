# Kiln

> Fine-tune, serve, and chat with open models on consumer hardware — one tool, one config.

Kiln is a CLI-first local AI workbench that turns a modest machine into a private LLM studio. One command surface covers the full loop that other tools split apart:

```
data in → model trained → model served → conversation out
```

- **Train** — QLoRA / LoRA / DPO fine-tuning on a consumer GPU
- **Serve** — OpenAI- and Anthropic-compatible APIs; GPU (native torch) or CPU (llama.cpp / GGUF)
- **Chat** — interactive TUI against a running server
- **Private by default** · Apache-2.0 · Linux and Windows first-class

!!! note
    The chat surface is a TUI today. The web dashboard and desktop shell are on the [roadmap](https://github.com/kiln-ai/kiln/blob/master/specs/project-plan.md).

## Highlights

- **One config file** — `kiln.yaml` drives training, serving, and eval; a content hash pins each run.
- **Train on what you have** — QLoRA (NF4) keeps 7–14B models trainable on a single consumer GPU.
- **Serve anywhere** — CPU backend (llama.cpp + GGUF) for no-GPU machines.
- **Eval gate** — `kiln ship` turns a threshold into a SHIP / DON'T-SHIP exit code.
- **MCP server** — expose Kiln tooling to MCP clients over stdio.
- **Light startup** — heavy deps are lazy-imported; CLI stays importable without torch.

## Quick links

- [Installation](getting-started/installation.md) — Python version, extras, verification
- [Quickstart](getting-started/quickstart.md) — fetch → lint → train → serve → chat
- [CLI Reference](cli/index.md) — every command and flag
- [Configuration](config/index.md) — `kiln.yaml` schema
- [Architecture](architecture/index.md) — gateway, engine, backends

## Hardware tiers

| Tier | Hardware | Models | Path |
|------|----------|--------|------|
| 1 | CPU-only, 8 GB RAM | 1–4B dense, OLMoE-class MoE | llama.cpp/GGUF |
| 2 | CPU-only, 16 GB RAM | 7–14B Q4 GGUF, 30B-A3B MoE | llama.cpp/GGUF |
| 3 | 4–6 GB VRAM GPU | 7–8B train + chat | native torch |
| 4 | 8–24 GB VRAM GPU | 8–14B+ everything | native torch |

`kiln doctor` detects the tier; `kiln plan` shows what a machine can run before downloading anything.

## License

Apache-2.0 — see `LICENSE`.
