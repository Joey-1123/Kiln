# Architecture

## Overview

```
┌──────────────────────────────────────────────────────────────┐
│ UX: CLI (Typer) · TUI chat · Web chat+dashboard (roadmap)    │
├──────────────────────────────────────────────────────────────┤
│ Gateway+Engine: V1 = ONE process, two async halves over      │
│   typed-dataclass messages on asyncio.Queue (A1); message    │
│   codec is numpy-only / torch-free (A2)                      │
│   API: OpenAI (/v1/chat/completions, tools) + Anthropic      │
├──────────────────────────────────────────────────────────────┤
│ Engine: scheduler · KV cache · sampling · ExpertBank         │
│   Backends: CUDA native (torch+Triton) · CPU (llama.cpp)    │
│   Transport seam: Queue → ZMQ (constructor change only)      │
├──────────────────────────────────────────────────────────────┤
│ Supervisor: torch-free process, crash isolation, ready-ack   │
└──────────────────────────────────────────────────────────────┘
```

Training: `src/kiln/trainer/` — SFT/DPO via QLoRA NF4 (peft/trl), lazy heavy imports inside functions so the CLI stays importable without torch.

## Repo layout

```
src/kiln/
  cli.py
  config/schema.py
  trainer/{sft,dpo,_compat}.py
  engine/{batching,decode_scheduler,cache_tier,expert_bank,messages,gateway,engine,transport_zmq,supervisor,__main__}
  engine/backends/{cuda_native,llama_cpp}.py
  engine/kernels/decode.py
  hub/{fetch,auth,preflight}.py
  data/{formats,lint,stats}.py
  quant/{quantize,apply}.py
  mcp_server/__init__.py
  chat/__init__.py
  tune/{measure,cache}.py
  models/{llama,qwen,gemma,phi,olmoe}
  utils/{paths,platform,exitcodes,budget,errors}
tests/   specs/   docs/   benchmarks/
```

## Key decisions

Locked in `specs/project-plan.md` v1.3. Highlights:

- **D1** Python core + Triton/native kernels
- **D4** GPU optional for serve/chat; required for >1B training
- **D5** QLoRA NF4 via peft/trl, SFT+DPO first; layer-streaming opt-in V2
- **D6** Placement/quant changes speed, never tokens (parity oracle gates)
- **D7** Dual backend: CUDA = torch+Triton (safetensors), CPU = embedded llama.cpp (GGUF)
- **A1** V1 gateway+engine fused over `asyncio.Queue`; ZMQ split deferred until MoE/TP/high-concurrency
- **A2** Message codec is numpy-only / torch-free (no `message.utils` torch coupling)

## Transport seam

`engine/messages.py` and `engine/transport_zmq.py` expose a `QueueTransport` / `ZmqTransport` behind a common interface. Swapping `asyncio.Queue` → ZMQ is a constructor change. `kiln serve` fuses gateway+engine in one process by default (`queue`); `--transport zmq` exercises the ZMQ wire path in-process; `--supervisor` moves the engine to a child process (`python -m kiln.engine`, ZMQ transport, gateway in parent, supervisor monitors the child with a READY/ACK pipe).

## References

- Locked plan: `specs/project-plan.md`
- Reference analysis: `specs/references-analysis.md`
