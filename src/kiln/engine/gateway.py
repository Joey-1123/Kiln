"""Kiln Gateway — FastAPI app, OpenAI/Anthropic-compatible API.

Agent-compat rules:
  - Anthropic streams end on message_stop (no [DONE] sentinel)
  - 15s SSE keepalive pings
  - Error envelope, not FastAPI default detail
  - Terminal-error-with-code guarantee

Security:
  - localhost bind default
  - startup API token (checked via header)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from kiln.engine.messages import (
    ChatMessage,
    GenerateComplete,
    GenerateError,
    GenerateRequest,
    HealthCheck,
    HealthResponse,
    LoadModelRequest,
    ModelLoaded,
    TokenDelta,
    ToolDefinition,
    Transport,
)
from kiln.engine.metrics import MetricsCollector, summarise

log = logging.getLogger(__name__)

_PendingFut = asyncio.Future[HealthResponse | GenerateComplete | GenerateError]

# ---------------------------------------------------------------------------
# Request/Response schemas (OpenAI-compatible)
# ---------------------------------------------------------------------------


class OpenAIChatMessage(BaseModel):
    """OpenAI chat message object (role + content)."""
    role: str
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None


class OpenAITool(BaseModel):
    """OpenAI tool definition object."""
    type: str = "function"
    function: dict[str, Any] = Field(default_factory=dict)


class OpenAIChatRequest(BaseModel):
    """OpenAI chat completion request envelope."""
    model: str = ""
    messages: list[OpenAIChatMessage] = []
    temperature: float = 0.7
    max_tokens: int = 512
    top_p: float = 1.0
    stream: bool = False
    tools: list[OpenAITool] | None = None
    stop: str | list[str] | None = None
    grammar: str = ""  # xgrammar / constrained-decoding spec (empty = unconstrained)


class OpenAIChoice(BaseModel):
    """A single OpenAI completion choice."""
    index: int = 0
    message: dict[str, Any] = Field(default_factory=dict)
    finish_reason: str = "stop"


class OpenAIUsage(BaseModel):
    """OpenAI token usage object."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class OpenAIChatResponse(BaseModel):
    """OpenAI chat completion response envelope."""
    id: str = ""
    object: str = "chat.completion"
    created: int = 0
    model: str = ""
    choices: list[OpenAIChoice] = []
    usage: OpenAIUsage = Field(default_factory=OpenAIUsage)


class OpenAIModel(BaseModel):
    """OpenAI model object."""
    id: str
    object: str = "model"
    created: int = 0
    owned_by: str = "kiln"


class OpenAIModelList(BaseModel):
    """OpenAI model list response."""
    object: str = "list"
    data: list[OpenAIModel] = []


class AnthropicMessage(BaseModel):
    """Anthropic message object."""
    role: str
    content: str | list[dict[str, Any]]


class AnthropicRequest(BaseModel):
    """Anthropic-style message request envelope."""
    model: str = ""
    messages: list[AnthropicMessage] = []
    max_tokens: int = 512
    temperature: float = 0.7
    stream: bool = False
    stop_sequences: list[str] | None = None
    grammar: str = ""  # xgrammar / constrained-decoding spec (empty = unconstrained)


class AnthropicContentBlock(BaseModel):
    """A content block within an Anthropic message."""
    type: str = "text"
    text: str = ""


class AnthropicResponse(BaseModel):
    """Anthropic message response envelope."""
    id: str = ""
    type: str = "message"
    role: str = "assistant"
    content: list[AnthropicContentBlock] = []
    model: str = ""
    stop_reason: str | None = "end_turn"
    usage: dict[str, int] = Field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})


class ErrorEnvelope(BaseModel):
    """Standard error envelope returned on failures."""
    error: dict[str, Any]


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------

_SSE_KEEPALIVE_SECONDS = 15


def _sse_format(data: dict, event: str | None = None) -> str:
    """Format a dict as an SSE message."""
    lines: list[str] = []
    if event:
        lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data)}")
    lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_gateway(
    *,
    transport: Transport,
    model_name: str = "default",
    api_token: str | None = None,
    response_transport: Transport | None = None,
) -> FastAPI:
    """Create the FastAPI gateway app.

    Parameters
    ----------
    transport : Transport
        The transport seam to the engine (gateway → engine direction).
    response_transport : Transport | None
        The engine → gateway transport for the response listener.
        If None, uses ``transport`` (for testing / single-transport setups).
    model_name : str
        Default model name to expose in /v1/models.
    api_token : str | None
        If set, require this token in X-API-Token header.
    """
    app = FastAPI(
        title="Kiln",
        description="OpenAI/Anthropic-compatible API for local models.",
        docs_url="/docs",
        redoc_url=None,
    )

    # Store state
    app.state.transport = transport
    app.state.model_name = model_name
    app.state.api_token = api_token
    app.state._pending: dict[str, _PendingFut] = {}
    app.state._response_transport = response_transport or transport
    app.state.metrics = MetricsCollector()

    # -----------------------------------------------------------------------
    # Auth middleware
    # -----------------------------------------------------------------------

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next: Any) -> Any:
        """Check API token if configured."""
        token = app.state.api_token
        if token and request.url.path not in ("/health", "/docs", "/openapi.json"):
            provided = request.headers.get("x-api-token", "")
            if provided != token:
                return JSONResponse(
                    status_code=401,
                    content={"error": {"code": "unauthorized", "message": "Invalid API token"}},
                )
        return await call_next(request)

    # -----------------------------------------------------------------------
    # Health
    # -----------------------------------------------------------------------

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Health check — hits the engine via transport."""
        req_id = str(uuid.uuid4())
        fut: asyncio.Future[HealthResponse] = asyncio.get_event_loop().create_future()
        app.state._pending[req_id] = fut
        try:
            await transport.put(HealthCheck(request_id=req_id))
            resp = await asyncio.wait_for(fut, timeout=5.0)
            return {
                "status": resp.status,
                "model_loaded": resp.model_loaded,
                "backend": resp.backend,
            }
        except asyncio.TimeoutError:
            return {"status": "timeout", "model_loaded": False, "backend": ""}
        finally:
            app.state._pending.pop(req_id, None)

    # -----------------------------------------------------------------------
    # Models
    # -----------------------------------------------------------------------

    @app.get("/v1/metrics")
    async def metrics() -> dict[str, Any]:
        """Serving metrics summary (TTFT / tok-s) for the dashboard."""
        return summarise(app.state.metrics.snapshot())

    @app.get("/v1/models")
    async def list_models() -> OpenAIModelList:
        """GET /v1/models handler — list available models."""
        return OpenAIModelList(data=[
            OpenAIModel(id=app.state.model_name, owned_by="kiln"),
        ])

    # -----------------------------------------------------------------------
    # Load model
    # -----------------------------------------------------------------------

    @app.post("/v1/load")
    async def load_model(body: dict[str, Any]) -> dict[str, Any]:
        """Load a model into the engine."""
        quant = body.get("quantization", "none")
        try:
            from kiln.quant.apply import build_quant_spec

            build_quant_spec(quant)
        except Exception as exc:
            from kiln.utils.errors import KilnError

            if isinstance(exc, KilnError):
                raise HTTPException(
                    status_code=400,
                    detail={"error": {"code": "invalid_quant", "message": exc.message}},
                )
            raise HTTPException(
                status_code=400,
                detail={"error": {"code": "invalid_quant", "message": str(exc)}},
            )
        req_id = str(uuid.uuid4())
        fut: asyncio.Future[ModelLoaded | GenerateError] = asyncio.get_event_loop().create_future()
        app.state._pending[req_id] = fut
        try:
            await transport.put(LoadModelRequest(
                request_id=req_id,
                model_path=body.get("model_path", ""),
                backend=body.get("backend", ""),
                quantization=quant,
            ))
            resp = await asyncio.wait_for(fut, timeout=300.0)
            if isinstance(resp, GenerateError):
                detail = {
                    "error": {"code": resp.error_code, "message": resp.error_message}
                }
                raise HTTPException(status_code=500, detail=detail)
            return {
                "status": "loaded",
                "model_path": resp.model_path,
                "backend": resp.backend,
            }
        except asyncio.TimeoutError:
            detail = {"error": {"code": "timeout", "message": "Model load timed out"}}
            raise HTTPException(status_code=504, detail=detail)
        finally:
            app.state._pending.pop(req_id, None)

    # -----------------------------------------------------------------------
    # OpenAI-compatible chat completions
    # -----------------------------------------------------------------------

    @app.post("/v1/chat/completions")
    async def openai_chat_completions(body: OpenAIChatRequest) -> Any:
        """OpenAI-compatible /v1/chat/completions endpoint."""
        req_id = str(uuid.uuid4())
        messages = tuple(
            ChatMessage(
                role=m.role,
                content=m.content or "",
                name=m.name,
                tool_call_id=m.tool_call_id,
            )
            for m in body.messages
        )
        stop = body.stop
        if isinstance(stop, str):
            stop = (stop,)
        elif isinstance(stop, list):
            stop = tuple(stop)
        else:
            stop = ()

        tools = tuple(
            ToolDefinition(type=t.type, function=t.function)
            for t in (body.tools or [])
        )

        gen_req = GenerateRequest(
            request_id=req_id,
            model=body.model or app.state.model_name,
            messages=messages,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            top_p=body.top_p,
            stream=body.stream,
            tools=tools,
            stop=stop,
            grammar=body.grammar,
        )
        app.state.metrics.start(req_id)

        if body.stream:
            return StreamingResponse(
                _stream_openai(gen_req, transport, app.state),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        # Non-streaming
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        app.state._pending[req_id] = fut
        try:
            await transport.put(gen_req)
            resp = await asyncio.wait_for(fut, timeout=60.0)
            if isinstance(resp, GenerateError):
                return JSONResponse(
                    status_code=500,
                    content={"error": {"code": resp.error_code, "message": resp.error_message}},
                )
            return OpenAIChatResponse(
                id=f"chatcmpl-{req_id}",
                created=int(time.time()),
                model=body.model or app.state.model_name,
                choices=[OpenAIChoice(message={"role": "assistant", "content": resp.text})],
                usage=OpenAIUsage(
                    prompt_tokens=resp.usage_prompt_tokens,
                    completion_tokens=resp.usage_completion_tokens,
                ),
            )
        except asyncio.TimeoutError:
            return JSONResponse(
                status_code=504,
                content={"error": {"code": "timeout", "message": "Generation timed out"}},
            )
        finally:
            app.state._pending.pop(req_id, None)
            app.state.metrics.finish(req_id)

    # -----------------------------------------------------------------------
    # Anthropic-compatible messages
    # -----------------------------------------------------------------------

    @app.post("/v1/messages")
    async def anthropic_messages(body: AnthropicRequest) -> Any:
        """Anthropic-compatible /v1/messages endpoint."""
        req_id = str(uuid.uuid4())
        messages = tuple(
            ChatMessage(
                role=m.role,
                content=m.content if isinstance(m.content, str) else json.dumps(m.content),
            )
            for m in body.messages
        )
        stop = tuple(body.stop_sequences) if body.stop_sequences else ()

        gen_req = GenerateRequest(
            request_id=req_id,
            model=body.model or app.state.model_name,
            messages=messages,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            stream=body.stream,
            stop=stop,
            grammar=body.grammar,
        )
        app.state.metrics.start(req_id)

        if body.stream:
            return StreamingResponse(
                _stream_anthropic(gen_req, transport, app.state),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        app.state._pending[req_id] = fut
        try:
            await transport.put(gen_req)
            resp = await asyncio.wait_for(fut, timeout=60.0)
            if isinstance(resp, GenerateError):
                err_detail = {
                    "type": "error",
                    "error": {"type": "api_error", "message": resp.error_message},
                }
                return JSONResponse(status_code=500, content=err_detail)
            return AnthropicResponse(
                id=f"msg_{req_id}",
                model=body.model or app.state.model_name,
                content=[AnthropicContentBlock(text=resp.text)],
                stop_reason="end_turn",
                usage={
                    "input_tokens": resp.usage_prompt_tokens,
                    "output_tokens": resp.usage_completion_tokens,
                },
            )
        except asyncio.TimeoutError:
            return JSONResponse(
                status_code=504,
                content={"error": {"code": "timeout", "message": "Generation timed out"}},
            )
        finally:
            app.state._pending.pop(req_id, None)
            app.state.metrics.finish(req_id)

    # -----------------------------------------------------------------------
    # Response listener (engine → gateway)
    # -----------------------------------------------------------------------

    @app.on_event("startup")  # type: ignore[no-untyped-decorator]
    async def _start_response_listener() -> None:
        """Background task that listens for engine responses."""
        asyncio.create_task(_response_loop(app.state._response_transport, app.state))

    return app


# ---------------------------------------------------------------------------
# Streaming generators
# ---------------------------------------------------------------------------


async def _stream_openai(
    req: GenerateRequest,
    transport: Transport,
    state: Any,
) -> Any:
    """Stream OpenAI SSE format."""
    # Register future for completion
    loop = asyncio.get_event_loop()
    fut: asyncio.Future[GenerateComplete | GenerateError] = loop.create_future()
    state._pending[req.request_id] = fut

    await transport.put(req)

    last_send = time.time()
    try:
        while True:
            try:
                # Wait for next token or timeout for keepalive
                token_coro = _get_next_token(
                    req.request_id, transport, state
                )
                msg = await asyncio.wait_for(
                    token_coro, timeout=_SSE_KEEPALIVE_SECONDS
                )
                if msg is None:
                    # Timeout — send keepalive
                    if time.time() - last_send >= _SSE_KEEPALIVE_SECONDS:
                        yield _sse_format({}, event="ping")
                        last_send = time.time()
                    continue

                last_send = time.time()
                if isinstance(msg, TokenDelta):
                    if msg.token:
                        state.metrics.token(req.request_id)
                    chunk = {
                        "id": f"chatcmpl-{req.request_id}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": req.model,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": msg.token} if msg.token else {},
                            "finish_reason": msg.finish_reason,
                        }],
                    }
                    yield _sse_format(chunk, event="message")
                    if msg.finish_reason:
                        break
                elif isinstance(msg, GenerateComplete):
                    break
                elif isinstance(msg, GenerateError):
                    error_chunk = {
                        "error": {"code": msg.error_code, "message": msg.error_message},
                    }
                    yield _sse_format(error_chunk, event="error")
                    break
            except asyncio.TimeoutError:
                # Keepalive ping
                if time.time() - last_send >= _SSE_KEEPALIVE_SECONDS:
                    yield _sse_format({}, event="ping")
                    last_send = time.time()
    finally:
        state._pending.pop(req.request_id, None)
        state.metrics.finish(req.request_id)
        yield "data: [DONE]\n\n"


async def _stream_anthropic(
    req: GenerateRequest,
    transport: Transport,
    state: Any,
) -> Any:
    """Stream Anthropic SSE format.

    Anthropic rules:
      - message_start → content_block_delta → message_stop
      - NO [DONE] sentinel
    """
    loop = asyncio.get_event_loop()
    fut: asyncio.Future[GenerateComplete | GenerateError] = loop.create_future()
    state._pending[req.request_id] = fut

    await transport.put(req)

    # Message start event
    yield _sse_format({
        "type": "message_start",
        "message": {
            "id": f"msg_{req.request_id}",
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": req.model,
            "stop_reason": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    }, event="message_start")

    last_send = time.time()
    try:
        while True:
            try:
                token_coro = _get_next_token(
                    req.request_id, transport, state
                )
                msg = await asyncio.wait_for(
                    token_coro, timeout=_SSE_KEEPALIVE_SECONDS
                )
                if msg is None:
                    if time.time() - last_send >= _SSE_KEEPALIVE_SECONDS:
                        yield _sse_format({}, event="ping")
                        last_send = time.time()
                    continue

                last_send = time.time()
                if isinstance(msg, TokenDelta) and msg.token:
                    state.metrics.token(req.request_id)
                    yield _sse_format({
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": msg.token},
                    }, event="content_block_delta")
                elif isinstance(msg, GenerateComplete):
                    break
                elif isinstance(msg, GenerateError):
                    yield _sse_format({
                        "type": "error",
                        "error": {"type": "api_error", "message": msg.error_message},
                    }, event="error")
                    break
            except asyncio.TimeoutError:
                if time.time() - last_send >= _SSE_KEEPALIVE_SECONDS:
                    yield _sse_format({}, event="ping")
                    last_send = time.time()
    finally:
        state._pending.pop(req.request_id, None)
        state.metrics.finish(req.request_id)
        # Anthropic: message_stop, NOT [DONE]
        yield _sse_format({"type": "message_stop"}, event="message_stop")


async def _get_next_token(
    request_id: str,
    transport: Transport,
    state: Any,
) -> TokenDelta | GenerateComplete | GenerateError | None:
    """Get the next token from the engine response queue.

    This is a simplified implementation.  In production, the engine
    would push to a per-request queue.  For V1, we use a shared
    response queue pattern.
    """
    # In the fused single-process design, the engine and gateway
    # share the event loop.  The engine pushes responses to a
    # per-request asyncio.Queue.
    q = getattr(state, "_response_queues", {}).get(request_id)
    if q is None:
        # Create the queue on first access
        if not hasattr(state, "_response_queues"):
            state._response_queues = {}
        q = asyncio.Queue(maxsize=256)
        state._response_queues[request_id] = q
    try:
        return await asyncio.wait_for(q.get(), timeout=0.1)
    except asyncio.TimeoutError:
        return None


# ---------------------------------------------------------------------------
# Response routing (called by engine callback)
# ---------------------------------------------------------------------------


def route_response(state: Any, msg: TokenDelta | GenerateComplete | GenerateError) -> None:
    """Route an engine response to the correct per-request queue.

    Called by the engine when it produces a response.
    """
    q = getattr(state, "_response_queues", {}).get(msg.request_id)
    if q is not None:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            log.warning("Response queue full for request %s", msg.request_id)


async def _response_loop(transport: Transport, state: Any) -> None:
    """Background loop that reads from the engine→gateway transport
    and routes each message to the correct per-request queue.

    This is the fused single-process bridge (A1). In the future ZMQ
    split, this loop would be replaced by a ZMQ subscriber.
    """
    while True:
        try:
            msg = await transport.get()
            route_response(state, msg)
        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("Error in response loop")
