"""Typed messages for gateway ↔ engine communication.

Every message is a frozen dataclass with a ``__type__`` discriminator.
The codec serialises to/from numpy-safe dicts; torch objects are
**never** part of the wire format (A2).

Transport seam: ``Transport`` is a Protocol with ``put()``/``get()``
identical for ``asyncio.Queue`` and a future ZMQ implementation.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np

# ---------------------------------------------------------------------------
# Message types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChatMessage:
    """A single message in a chat conversation."""

    role: str  # "system" | "user" | "assistant" | "tool"
    content: str = ""
    name: str | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolDefinition:
    """OpenAI-style tool definition."""

    type: str = "function"
    function: dict = field(default_factory=dict)


@dataclass(frozen=True)
class GenerateRequest:
    """Gateway → Engine: start a generation."""

    __type__: str = field(default="GenerateRequest", init=False)
    request_id: str = ""
    model: str = ""
    messages: tuple[ChatMessage, ...] = ()
    temperature: float = 0.7
    max_tokens: int = 512
    top_p: float = 1.0
    stream: bool = False
    tools: tuple[ToolDefinition, ...] = ()
    stop: tuple[str, ...] = ()


@dataclass(frozen=True)
class TokenDelta:
    """Engine → Gateway: a streaming token."""

    __type__: str = field(default="TokenDelta", init=False)
    request_id: str = ""
    token: str = ""
    finish_reason: str | None = None


@dataclass(frozen=True)
class GenerateComplete:
    """Engine → Gateway: generation finished."""

    __type__: str = field(default="GenerateComplete", init=False)
    request_id: str = ""
    text: str = ""
    finish_reason: str = "stop"
    usage_prompt_tokens: int = 0
    usage_completion_tokens: int = 0


@dataclass(frozen=True)
class GenerateError:
    """Engine → Gateway: generation failed."""

    __type__: str = field(default="GenerateError", init=False)
    request_id: str = ""
    error_code: str = "internal_error"
    error_message: str = ""


@dataclass(frozen=True)
class HealthCheck:
    """Gateway → Engine: are you alive?"""

    __type__: str = field(default="HealthCheck", init=False)
    request_id: str = ""


@dataclass(frozen=True)
class HealthResponse:
    """Engine → Gateway: health status."""

    __type__: str = field(default="HealthResponse", init=False)
    request_id: str = ""
    status: str = "ok"
    model_loaded: bool = False
    backend: str = ""


@dataclass(frozen=True)
class LoadModelRequest:
    """Gateway → Engine: load a model into memory."""

    __type__: str = field(default="LoadModelRequest", init=False)
    request_id: str = ""
    model_path: str = ""
    backend: str = ""  # "cuda" | "cpu" | "" for auto


@dataclass(frozen=True)
class ModelLoaded:
    """Engine → Gateway: model loaded successfully."""

    __type__: str = field(default="ModelLoaded", init=False)
    request_id: str = ""
    model_path: str = ""
    backend: str = ""


# Union of all message types
EngineMessage = (
    GenerateRequest
    | TokenDelta
    | GenerateComplete
    | GenerateError
    | HealthCheck
    | HealthResponse
    | LoadModelRequest
    | ModelLoaded
)

# Registry for deserialisation
_MSG_TYPES: dict[str, type] = {
    cls.__dataclass_fields__["__type__"].default: cls  # type: ignore[index]
    for cls in [
        GenerateRequest,
        TokenDelta,
        GenerateComplete,
        GenerateError,
        HealthCheck,
        HealthResponse,
        LoadModelRequest,
        ModelLoaded,
    ]
}

#_guard: client-injected __type__ injection
_ALLOWED_TYPES = set(_MSG_TYPES.keys())


# ---------------------------------------------------------------------------
# Serialisation (numpy-only, torch-free)
# ---------------------------------------------------------------------------

def _numpy_safe(obj: object) -> object:
    """Convert numpy types to JSON-safe Python primitives."""
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def serialize(msg: EngineMessage) -> dict:
    """Serialize a message to a JSON-safe dict."""
    d = asdict(msg)
    # Ensure __type__ is present (it's a field with default, but be explicit)
    if "__type__" not in d:
        d["__type__"] = type(msg).__name__
    return json.loads(json.dumps(d, default=_numpy_safe))


def deserialize(data: dict) -> EngineMessage:
    """Deserialize a dict back into a typed message.

    Raises ValueError if ``__type__`` is missing, unknown, or injected
    by a client (the injection guard).
    """
    msg_type = data.get("__type__")
    if not isinstance(msg_type, str):
        raise ValueError("Message missing '__type__' discriminator")
    if msg_type not in _ALLOWED_TYPES:
        raise ValueError(f"Unknown message type: {msg_type!r}")
    cls = _MSG_TYPES[msg_type]
    # Filter to only fields the dataclass accepts; __type__ is init=False
    known = set(cls.__dataclass_fields__.keys()) - {"__type__"}
    filtered = {k: v for k, v in data.items() if k in known}
    return cls(**filtered)


# ---------------------------------------------------------------------------
# Transport seam (Protocol — identical for Queue and future ZMQ)
# ---------------------------------------------------------------------------

@runtime_checkable
class Transport(Protocol):
    """Transport interface — put/get over typed messages."""

    async def put(self, msg: EngineMessage) -> None: ...
    async def get(self) -> EngineMessage: ...


class QueueTransport:
    """asyncio.Queue-based transport (V1 default)."""

    def __init__(self, maxsize: int = 64) -> None:
        self._q: asyncio.Queue[EngineMessage] = asyncio.Queue(maxsize=maxsize)

    async def put(self, msg: EngineMessage) -> None:
        """Put a message onto the transport."""
        await self._q.put(msg)

    async def get(self) -> EngineMessage:
        """Get the next message from the transport (blocks)."""
        return await self._q.get()
