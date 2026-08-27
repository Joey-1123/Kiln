"""Tests for the ZeroMQ transport seam (plan A1).

These exercise the real pyzmq-backed Transport: wire round-trips for every
message type, the deserialise injection guard, and an end-to-end Engine
health check over a ZmqLink (proving the gateway↔engine wire path without a
real model).
"""

import asyncio

import pytest

from kiln.engine.messages import (
    ChatMessage,
    EngineMessage,
    GenerateComplete,
    GenerateError,
    GenerateRequest,
    HealthCheck,
    HealthResponse,
    LoadModelRequest,
    ModelLoaded,
    TokenDelta,
    deserialize,
    serialize,
)
from kiln.engine.transport_zmq import ZmqLink, ZmqTransport

_PORT = 5717


def _all_messages() -> list[EngineMessage]:
    return [
        HealthCheck(request_id="r1"),
        HealthResponse(request_id="r1", status="ok", model_loaded=False, backend=""),
        LoadModelRequest(request_id="r2", model_path="/m", backend=""),
        ModelLoaded(request_id="r2", model_path="/m", backend="cpu"),
        GenerateRequest(
            request_id="r3",
            messages=[ChatMessage(role="user", content="hi")],
            max_tokens=8,
            temperature=0.0,
        ),
        TokenDelta(request_id="r3", token="x", finish_reason="stop"),
        GenerateComplete(request_id="r3", text="hi", finish_reason="stop"),
        GenerateError(request_id="r3", error_code="e", error_message="boom"),
    ]


@pytest.mark.asyncio
async def test_zmq_roundtrip_all_types():
    a = f"tcp://127.0.0.1:{_PORT}"
    server = ZmqTransport(a, bind=True)
    client = ZmqTransport(a, bind=False)
    try:
        for msg in _all_messages():
            await client.put(msg)
            got = await asyncio.wait_for(server.get(), timeout=5)
            # Wire equality: the JSON codec normalises nested dataclasses to
            # dicts, so compare the serialised form (mirrors QueueTransport).
            assert serialize(got) == serialize(msg)
            # round-trip the other direction too
            await server.put(msg)
            got2 = await asyncio.wait_for(client.get(), timeout=5)
            assert serialize(got2) == serialize(msg)
    finally:
        await server.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_zmq_injection_guard():
    # The codec refuses unknown/impersonated message types on the wire.
    with pytest.raises(ValueError):
        deserialize({"__type__": "EvilThing", "x": 1})

    a = f"tcp://127.0.0.1:{_PORT + 1}"
    server = ZmqTransport(a, bind=True)
    client = ZmqTransport(a, bind=False)
    try:
        client._ensure()  # noqa: SLF001
        server._ensure()  # noqa: SLF001
        await client._socket.send_json({"__type__": "EvilThing", "x": 1})  # noqa: SLF001
        with pytest.raises(ValueError):
            await asyncio.wait_for(server.get(), timeout=5)
    finally:
        await server.aclose()
        await client.aclose()


@pytest.mark.asyncio
async def test_zmq_link_end_to_end_health():
    from kiln.engine.engine import Engine

    link = ZmqLink(port_a=_PORT + 2, port_b=_PORT + 3)
    engine = Engine(
        gateway_transport=link.engine_from_gateway,
        engine_transport=link.engine_to_gateway,
    )
    task = asyncio.create_task(engine.run())
    try:
        await link.gateway_to_engine.put(HealthCheck(request_id="h1"))
        resp = await asyncio.wait_for(link.gateway_from_engine.get(), timeout=5)
        assert isinstance(resp, HealthResponse)
        assert resp.request_id == "h1"
        assert resp.status == "ok"
    finally:
        engine.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await link.aclose()


def test_zmq_link_connect_to_constructs():
    link = ZmqLink.connect_to("192.168.0.5", port_a=5800, port_b=5801)
    # engine side connects (never binds) — all four transports are clients
    for t in (
        link.gateway_to_engine,
        link.engine_from_gateway,
        link.engine_to_gateway,
        link.gateway_from_engine,
    ):
        assert t._bind is False  # noqa: SLF001
    a, b = link.endpoints()
    assert a == "tcp://127.0.0.1:5800"
    assert b == "tcp://127.0.0.1:5801"
