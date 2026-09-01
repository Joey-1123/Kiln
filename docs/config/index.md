# Configuration

Kiln is driven by a single `kiln.yaml`. The schema lives in `src/kiln/config/schema.py` and is the single source of truth — every field validated by Pydantic v2 with `extra="forbid"`.

## Layout

Recipe fields and eval/gate policy are separated at the top level so a semantic fingerprint (`config_sha`) can hash the recipe alone, excluding policy that does not affect weights:

```yaml
recipe:
  model:
    base: meta-llama/Llama-3.1-8B-Instruct
    arch: null          # auto-detected when omitted
  data:
    train: ./data/train.jsonl
    format: auto        # auto | alpaca | chatml | sharegpt | plain
    val_split: 0.1
  training:
    epochs: 3
    lr: 0.00002
    batch_size: 4       # int or "auto"
    quantization: 4bit  # none | 8bit | 4bit | gptq | awq
    seed: 1234
    layer_streaming: false
    lora:
      r: 16
      alpha: 16
      dropout: 0.05
  serve:
    host: "127.0.0.1"
    port: 8000
    context_length: 4096
  output:
    dir: ./output

eval:
  ship:
    metric_threshold: 0.0
```

Create one interactively or from a template:

```bash
kiln init                          # interactive
kiln init -t train -m MODEL -d DATA -c kiln.yaml -f
kiln plan --write-config kiln.yaml # scaffold from hardware detection
```

## Validation

```python
from kiln.config import load_config

cfg = load_config("kiln.yaml")
```

Use `config_to_yaml(cfg)` for a canonical round-trip. `load_config` raises `FileNotFoundError` or `pydantic.ValidationError` on bad input.

## Fingerprinting

`kiln.config.config_sha` hashes the `recipe` block only. Changing `eval.ship.metric_threshold` does not invalidate evidence about unchanged weights.

## Conventions

- `recipe.training.lora` holds rank/alpha/dropout; `alpha` conventionally `>= r`.
- `recipe.serve.host` defaults to `127.0.0.1` (security default — bind to a network interface explicitly).
- Unknown top-level or nested keys are rejected (`extra="forbid"`).
