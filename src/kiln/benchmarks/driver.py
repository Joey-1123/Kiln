"""V2 serving benchmarks — measure honest TTFT / tok/s / memory bars.

Drives the real serving stack — engine loop + gateway over in-process
transports, exactly as ``kiln serve`` and the V2-5 e2e test do — through the
public HTTP surface, so the numbers in ``/v1/metrics`` are the same ones a
production client observes. Supports the llama.cpp CPU backend and the torch
CUDA backend; loading is compulsory (a ``--model`` must be given and the chosen
backend must be able to load it, otherwise the run fails loudly).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx
from httpx import ASGITransport

from kiln.engine.engine import Engine
from kiln.engine.gateway import _response_loop, create_gateway
from kiln.engine.messages import QueueTransport
from kiln.engine.metrics import MemoryBars

log = logging.getLogger(__name__)

PROMPT = "Write a short sentence explaining what a mixture of experts is."


@dataclass(frozen=True)
class BenchmarkResult:
    """Aggregated serving benchmark for one backend/model run."""

    backend: str
    model: str
    requests: int
    avg_ttft: float
    avg_tokens_per_second: float
    memory: MemoryBars
    total_seconds: float


def _offload_bars(engine: Engine):
    def _snapshot() -> MemoryBars:
        coord = engine.offload
        if coord is None:
            return MemoryBars()
        stats = coord.stats()
        return MemoryBars(
            gpu_used_bytes=stats.gpu_used_bytes,
            gpu_capacity_bytes=stats.gpu_capacity_bytes,
            resident_experts=stats.resident_experts,
            registered_experts=stats.registered_experts,
            phase=stats.phase,
        )

    return _snapshot


async def _load_model(engine: Engine, backend: str, model_path: str, quant: str) -> None:
    """Load a model into the engine backend through the serving request path.

    Routes a ``LoadModelRequest`` through the engine's real loop (the same
    seam ``/v1/load`` exercises) so backend selection and load are identical
    to production. Raises RuntimeError if the backend is unavailable or the
    model fails to load (compulsory).
    """
    from kiln.engine.messages import GenerateError, LoadModelRequest, ModelLoaded

    await engine._gw.put(  # noqa: SLF001
        LoadModelRequest(  # type: ignore[arg-type]
            request_id="bench-load",
            model_path=model_path,
            backend=backend,
            quantization=quant,
        )
    )
    # Wait for the engine's reply to confirm success/failure.
    for _ in range(5):
        try:
            msg = await asyncio.wait_for(engine._eng.get(), timeout=120.0)  # noqa: SLF001
        except asyncio.TimeoutError:
            continue
        if isinstance(msg, ModelLoaded):
            return
        if isinstance(msg, GenerateError):
            raise RuntimeError(f"model load failed: {msg.error_code}: {msg.error_message}")
    raise RuntimeError(
        f"no backend could load {model_path!r} (backend={backend!r}) — "
        "is the model a compatible GGUF (CPU) or torch checkpoint (GPU)?"
    )


async def _run_single(
    client: httpx.AsyncClient, max_tokens: int
) -> tuple[float, int]:
    """Run one non-streaming chat completion; return (elapsed_s, output_tokens)."""
    started = time.monotonic()
    resp = await client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": PROMPT}],
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "stream": False,
        },
    )
    elapsed = time.monotonic() - started
    if resp.status_code != 200:
        raise RuntimeError(f"benchmark request failed: HTTP {resp.status_code}: {resp.text}")
    body = resp.json()
    text = body["choices"][0]["message"]["content"] or ""
    return elapsed, len(text.split())


async def run_benchmark(
    *,
    backend: str,
    model: str,
    requests: int = 20,
    max_tokens: int = 128,
    quantization: str = "none",
) -> BenchmarkResult:
    """Run a compulsory serving benchmark and return the aggregated result."""
    engine_out = QueueTransport()
    gw_out = QueueTransport()
    engine = Engine(gateway_transport=gw_out, engine_transport=engine_out)

    app = create_gateway(
        transport=gw_out,
        model_name="bench",
        response_transport=engine_out,
        offload_stats=_offload_bars(engine),
    )

    engine_task = asyncio.create_task(engine.run())
    listener: asyncio.Task | None = None
    try:
        # Load the model first, draining its own reply, *before* the response
        # listener starts consuming from the same engine→gateway transport.
        await _load_model(engine, backend, model, quantization)

        import httpx as _httpx

        listener = asyncio.create_task(_response_loop(engine_out, app.state))
        try:
            async with _httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://bench"
            ) as client:
                t0 = time.monotonic()
                first_token_total = 0.0
                first_count = 0
                tokens_total = 0
                for _ in range(requests):
                    elapsed, out_tokens = await asyncio.wait_for(
                        _run_single(client, max_tokens),
                        timeout=max(300.0, max_tokens * 30.0),
                    )
                    tokens_total += out_tokens
                    first_token_total += elapsed
                    first_count += 1
                total_seconds = time.monotonic() - t0
        finally:
            listener.cancel()
            listener = None

            # Pull the aggregated /v1/metrics for memory bars + server latency.
            async with _httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://bench"
            ) as client:
                m = (await client.get("/v1/metrics")).json()

        memory = MemoryBars(
            gpu_used_bytes=int(m.get("gpu_used_bytes", 0)),
            gpu_capacity_bytes=int(m.get("gpu_capacity_bytes", 0)),
            resident_experts=int(m.get("resident_experts", 0)),
            registered_experts=int(m.get("registered_experts", 0)),
            phase=m.get("phase", ""),
        )
        avg_ttft = first_token_total / first_count if first_count else 0.0
        avg_tokens_per_second = tokens_total / total_seconds if total_seconds else 0.0

        return BenchmarkResult(
            backend=backend,
            model=model,
            requests=requests,
            avg_ttft=avg_ttft,
            avg_tokens_per_second=avg_tokens_per_second,
            memory=memory,
            total_seconds=total_seconds,
        )
    finally:
        engine.stop()
        engine_task.cancel()
        if listener is not None:
            listener.cancel()
            tasks = (engine_task, listener)
        else:
            tasks = (engine_task,)
        await asyncio.gather(*tasks, return_exceptions=True)


def as_dict(result: BenchmarkResult) -> dict:
    """Serialize a benchmark result to a plain dict (for JSON output)."""
    return {
        "backend": result.backend,
        "model": result.model,
        "requests": result.requests,
        "avg_ttft_s": result.avg_ttft,
        "avg_tokens_per_second": result.avg_tokens_per_second,
        "total_seconds": result.total_seconds,
        "memory": {
            "gpu_used_bytes": result.memory.gpu_used_bytes,
            "gpu_capacity_bytes": result.memory.gpu_capacity_bytes,
            "resident_experts": result.memory.resident_experts,
            "registered_experts": result.memory.registered_experts,
            "phase": result.memory.phase,
        },
    }
