# Kiln

Kiln is a local AI workbench that turns consumer hardware into a private LLM studio:
**fine-tune** open models (8B–14B) on a modest GPU with one config file, **serve** them
through OpenAI/Anthropic-compatible APIs, and **chat** anywhere — gaming PC, laptop, or
even a no-GPU machine.

One tool covers the full loop other tools split apart:

```
data in  →  model trained  →  model served  →  conversation out
```

- **Train** — QLoRA / LoRA / DPO fine-tuning on consumer GPUs (Soup-style ladder)
- **Serve** — OpenAI + Anthropic compatible APIs; GPU (native torch) or CPU (llama.cpp / GGUF)
- **Chat** — TUI, web dashboard, and Tauri desktop shell
- **Private by default** · Apache-2.0 · Windows + Linux first-class

## Status

Planning / early build. The full v1–v3 roadmap lives in [`specs/project-plan.md`](specs/project-plan.md).

## Quick orientation

| Path | What |
|---|---|
| `specs/project-plan.md` | The definitive project plan (vision, decisions, milestones) |
| `specs/references-analysis.md` | Reverse-engineered analysis of the three reference projects |
| `references/` | Cloned reference repos (Soup, colibri, FreeToken) — *not part of Kiln* |
| `NOTICE` | Attribution to the reference projects |

## References (design inspiration only, not vendored)

Kiln is designed by studying three open-source projects (cloned locally under `references/`,
analyzed in `specs/references-analysis.md`, **not** copied or forked):

- [Soup](https://github.com/MakazhanAlpamys/Soup) — LLM fine-tuning CLI (config discipline, QLoRA ladder, eval gating)
- [colibri](https://github.com/JustVugg/colibri) — pure-C MoE inference engine (memory-tiering, weight streaming, semantics-preserving invariant)
- [FreeToken](https://github.com/FlashML-org/FreeToken) — edge-native MoE serving engine (process topology, capability matrices, elastic VRAM)

Each is Apache-2.0, the same license as Kiln. See `NOTICE` for full attribution.

## Shell completion

`kiln` ships with built-in shell completions (Typer/Click). Enable them for your shell:

```bash
# bash
eval "$(_KILN_COMPLETE=source_bash kiln)"

# zsh
eval "$(_KILN_COMPLETE=source_zsh kiln)"

# fish
_KILN_COMPLETE=source_fish kiln | source
```

Add the relevant line to your shell's rc file to persist.

