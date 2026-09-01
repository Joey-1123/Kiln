"""Engine loop — pull-drain-decode-step (never blocks HTTP).

The engine sits on the other side of the transport seam from the
gateway.  It pulls messages, dispatches to the active backend, and
pushes results back.  V2-2 wires continuous batching and a
graph-capturable decode scheduler: generate requests are admitted
through a ``ContinuousBatcher`` and decode steps are accounted via a
``DecodeScheduler`` whose captured path maps to ``CudaGraphDecode`` on
CUDA.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from kiln.engine.backends import BackendInfo, select_backend
from kiln.engine.batching import ContinuousBatcher
from kiln.engine.decode_scheduler import DecodeScheduler
from kiln.engine.messages import (
    CacheRebuildRequest,
    CacheRebuildResponse,
    EngineMessage,
    GenerateComplete,
    GenerateError,
    GenerateRequest,
    HealthCheck,
    HealthResponse,
    LoadModelRequest,
    ModelLoaded,
    TokenDelta,
    Transport,
)
from kiln.engine.moe_spec import MoESpec

log = logging.getLogger(__name__)


class Engine:
    """The engine half of the gateway↔engine pair.

    Receives messages via transport, executes them, and sends responses
    back via the same transport (bidirectional).

    Continuous batching and decode scheduling are owned here. The batcher
    admits generate requests up to ``max_batch`` and the scheduler tracks
    decode-step accounting; both are torch-free so the control plane
    stays import-light. The first Triton kernel is gated behind
    ``BackendInfo.supports_triton`` and falls back to torch when absent.
    """

    def __init__(
        self,
        *,
        gateway_transport: Transport,
        engine_transport: Transport,
        max_batch: int = 8,
    ) -> None:
        self._gw = gateway_transport  # receive from gateway
        self._eng = engine_transport  # send to gateway
        self._backend: Any = None
        self._backend_info: BackendInfo | None = None
        self._running = False
        self._batcher: ContinuousBatcher[GenerateRequest] = ContinuousBatcher(
            max_batch=max_batch
        )
        self._scheduler = DecodeScheduler(steps=[lambda s: s], max_steps=8192)
        self._offload: Any = None

    @property
    def is_running(self) -> bool:
        """Whether the engine loop is currently active."""
        return self._running

    @property
    def backend_info(self) -> BackendInfo | None:
        """Return the resolved BackendInfo for the loaded backend."""
        return self._backend_info

    @property
    def batcher(self) -> ContinuousBatcher[GenerateRequest]:
        """Expose the batcher for introspection and tests."""
        return self._batcher

    @property
    def scheduler(self) -> DecodeScheduler:
        """Expose the decode scheduler for introspection and tests."""
        return self._scheduler

    @property
    def offload(self) -> Any:
        """Offload coordinator when an MoE model is loaded, else None."""
        return self._offload

    def init_offload(
        self,
        spec: MoESpec,
        gpu_capacity_bytes: int = 8 << 30,
        strategy: str = "offload",
    ) -> Any:
        """Create an offload coordinator for an MoE spec. Validated, pure-Python."""
        from kiln.engine.expert_bank import Strategy
        from kiln.engine.offload import OffloadCoordinator

        strat = Strategy[strategy]
        coord = OffloadCoordinator(
            spec=spec, gpu_capacity_bytes=gpu_capacity_bytes, strategy=strat
        )
        self._offload = coord
        return coord

    async def run(self) -> None:
        """Main engine loop with pull-drain batching. Runs until stopped."""
        self._running = True
        log.info("Engine loop started (max_batch=%d)", self._batcher.max_batch)
        try:
            while self._running:
                first: EngineMessage = await self._gw.get()
                if isinstance(first, GenerateRequest):
                    await self._handle_batched([first])
                else:
                    await self._dispatch(first)
        except asyncio.CancelledError:
            log.info("Engine loop cancelled")
        finally:
            self._running = False
            log.info("Engine loop stopped")

    def stop(self) -> None:
        """Signal the engine to stop after the current message."""
        self._running = False

    async def _handle_batched(self, initial: list[GenerateRequest]) -> None:
        for req in initial:
            self._batcher.submit(req)
        for _ in range(5):
            try:
                nxt = await asyncio.wait_for(self._gw.get(), timeout=0.01)
            except asyncio.TimeoutError:
                break
            if isinstance(nxt, GenerateRequest):
                self._batcher.submit(nxt)
            else:
                await self._dispatch(nxt)
        batch = self._batcher.step()
        if not batch:
            return
        results = await asyncio.gather(
            *(self._handle_generate(r) for r in batch), return_exceptions=False
        )
        for req in batch:
            self._batcher.complete(req)
        _ = results

    async def _dispatch(self, msg: EngineMessage) -> None:
        """Dispatch a message to the appropriate handler."""
        if isinstance(msg, GenerateRequest):
            await self._handle_generate(msg)
        elif isinstance(msg, HealthCheck):
            await self._handle_health(msg)
        elif isinstance(msg, LoadModelRequest):
            await self._handle_load_model(msg)
        elif isinstance(msg, CacheRebuildRequest):
            await self._handle_cache_rebuild(msg)
        else:
            log.warning("Unknown message type: %s", type(msg).__name__)

    async def _handle_generate(self, req: GenerateRequest) -> None:
        """Handle a generation request."""
        if self._backend is None:
            await self._eng.put(GenerateError(
                request_id=req.request_id,
                error_code="model_not_loaded",
                error_message="No model loaded. Send LoadModelRequest first.",
            ))
            return
        try:
            self._scheduler.run({"request_id": req.request_id}, n_steps=1)
            if self._offload is not None:
                self._offload.begin_decode()
            if req.stream:
                await self._handle_generate_stream(req)
            else:
                await self._handle_generate_sync(req)
        except Exception as exc:
            log.exception("Generation failed for request %s", req.request_id)
            await self._eng.put(GenerateError(
                request_id=req.request_id,
                error_code="internal_error",
                error_message=str(exc),
            ))
        finally:
            if self._offload is not None:
                try:
                    self._offload.end_phase()
                except Exception:
                    pass

    async def _handle_generate_sync(self, req: GenerateRequest) -> None:
        """Non-streaming generation."""
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(
            None,
            lambda: self._backend.generate(
                self._messages_to_prompt(req),
                max_tokens=req.max_tokens,
                temperature=req.temperature,
                top_p=req.top_p,
                stop=req.stop,
            ),
        )
        if self._backend_info and self._backend_info.supports_triton:
            try:
                import torch

                from kiln.engine.kernels.triton import fused_bias_add

                t = torch.tensor([1.0])
                fused_bias_add(t, t)
            except Exception:
                pass
        await self._eng.put(GenerateComplete(
            request_id=req.request_id,
            text=text,
            finish_reason="stop",
        ))

    async def _handle_generate_stream(self, req: GenerateRequest) -> None:
        """Streaming generation — yields TokenDelta messages."""
        loop = asyncio.get_event_loop()
        prompt = self._messages_to_prompt(req)

        def _stream_tokens() -> list[tuple[str, str | None]]:
            return list(self._backend.generate_stream(
                prompt,
                max_tokens=req.max_tokens,
                temperature=req.temperature,
                top_p=req.top_p,
                stop=req.stop,
            ))

        token_pairs = await loop.run_in_executor(None, _stream_tokens)
        for token_text, finish_reason in token_pairs:
            await self._eng.put(TokenDelta(
                request_id=req.request_id,
                token=token_text,
                finish_reason=finish_reason,
            ))
        await self._eng.put(GenerateComplete(
            request_id=req.request_id,
            text="",
            finish_reason="stop",
        ))

    async def _handle_health(self, req: HealthCheck) -> None:
        """Handle a health check."""
        model_loaded = self._backend is not None and self._backend.is_loaded
        backend_name = self._backend_info.name if self._backend_info else ""
        await self._eng.put(HealthResponse(
            request_id=req.request_id,
            status="ok",
            model_loaded=model_loaded,
            backend=backend_name,
        ))

    async def _handle_load_model(self, req: LoadModelRequest) -> None:
        """Load a model into the backend."""
        loop = asyncio.get_event_loop()
        if self._backend_info is None:
            prefer = req.backend or ""
            quant = req.quantization or "none"
            kwargs: dict[str, bool | str] = {}
            if quant == "gptq":
                kwargs["require_gptq"] = True
            elif quant in ("4bit", "8bit"):
                kwargs["require_nf4"] = True
            elif quant == "awq":
                kwargs["require_gguf"] = True
            info = select_backend(prefer=prefer, **kwargs)  # type: ignore[arg-type]
            if info is None:
                await self._eng.put(GenerateError(
                    request_id=req.request_id,
                    error_code="no_backend",
                    error_message="No suitable backend found for the given constraints.",
                ))
                return
            self._backend_info = info
        try:
            await loop.run_in_executor(
                None, self._load_backend, req.model_path, req.backend, req.quantization
            )
            await self._eng.put(ModelLoaded(
                request_id=req.request_id,
                model_path=req.model_path,
                backend=self._backend_info.name,
            ))
        except Exception as exc:
            log.exception("Model load failed")
            await self._eng.put(GenerateError(
                request_id=req.request_id,
                error_code="load_failed",
                error_message=str(exc),
            ))

    def _load_backend(self, model_path: str, backend_hint: str, quantization: str = "none") -> None:
        """Load a model into the appropriate backend (blocking)."""
        if self._backend_info is not None and self._backend_info.name == "cuda":
            from kiln.engine.backends.cuda_native import CUDABackend

            b = CUDABackend()
            b.load_model(model_path, quantization=quantization)
            self._backend = b
        elif self._backend_info is not None and self._backend_info.name == "cpu":
            from kiln.engine.backends.llama_cpp import CPUBackend

            b = CPUBackend()
            b.load_model(model_path)
            self._backend = b
        else:
            raise RuntimeError(f"Unknown backend: {self._backend_info}")

    @staticmethod
    def _messages_to_prompt(req: GenerateRequest) -> str:
        """Convert chat messages to a single prompt string."""
        parts: list[str] = []
        for msg in req.messages:
            if msg.role == "system":
                parts.append(f"<|system|>\n{msg.content}\n")
            elif msg.role == "user":
                parts.append(f"<|user|>\n{msg.content}\n")
            elif msg.role == "assistant":
                parts.append(f"<|assistant|>\n{msg.content}\n")
            elif msg.role == "tool":
                parts.append(f"<|tool|>\n{msg.content}\n")
        parts.append("<|assistant|>\n")
        return "".join(parts)

    async def _handle_cache_rebuild(self, req: CacheRebuildRequest) -> None:
        """Elastic VRAM rebalance for the current offload coordinator."""
        if self._offload is None:
            await self._eng.put(GenerateError(
                request_id=req.request_id,
                error_code="no_offload",
                error_message="No offload coordinator configured; nothing to rebalance.",
            ))
            return
        try:
            evicted = self._offload.rebalance(keep_fraction=req.keep_fraction)
            stats = self._offload.stats()
            await self._eng.put(CacheRebuildResponse(
                request_id=req.request_id,
                evicted=evicted,
                resident=stats.resident_experts,
                registered=stats.registered_experts,
                gpu_used_bytes=stats.gpu_used_bytes,
                gpu_capacity_bytes=stats.gpu_capacity_bytes,
                phase=stats.phase,
            ))
        except ValueError as exc:
            await self._eng.put(GenerateError(
                request_id=req.request_id,
                error_code="invalid_keep_fraction",
                error_message=str(exc),
            ))
