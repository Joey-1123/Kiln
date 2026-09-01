# Quickstart

Minimal end-to-end flow. Training requires a CUDA GPU; serving and chat do not.

```bash
# 1. Authenticate for gated models (e.g. Llama 3)
kiln login --token hf_xxx

# 2. Pull a base model (resumable, with disk-space preflight)
kiln fetch meta-llama/Llama-3.1-8B-Instruct

# 3. Validate a dataset before spending GPU time
kiln data lint data/train.jsonl
kiln data inspect data/train.jsonl
kiln data preview data/train.jsonl -n 3

# 4. Fine-tune (writes a LoRA adapter)
kiln train -c kiln.yaml -m sft

# 5. Serve an OpenAI-compatible API
kiln serve --model meta-llama/Llama-3.1-8B-Instruct --port 8000

# 6. Chat in the TUI
kiln chat --server http://localhost:8000
```

!!! tip "No GPU?"
    `kiln plan` reports what your machine can serve *before* you download anything, and `kiln export-gguf` produces a quantized GGUF you can run on CPU.

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

Interactive API docs at `http://localhost:8000/docs`.

!!! warning
    `kiln serve` binds to `127.0.0.1` by default. Expose on a network interface only on a trusted network, and protect it with `--token` if auth is configured.

## Next steps

- [CLI Reference](../cli/index.md) — full command list
- [Configuration](../config/index.md) — `kiln.yaml` layout
- `kiln doctor --deep` — readiness checks
- `kiln tune` — bandwidth self-calibration (GPU-UUID-keyed cache)
