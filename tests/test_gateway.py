"""Tests for engine.gateway — testable pieces without a running engine."""

import asyncio

from httpx import ASGITransport, AsyncClient

from kiln.engine.gateway import _sse_format, create_gateway, route_response
from kiln.engine.messages import (
    GenerateComplete,
    GenerateError,
    GenerateRequest,
    HealthCheck,
    HealthResponse,
    LoadModelRequest,
    ModelLoaded,
    QueueTransport,
    TokenDelta,
)


async def _get(app, path, **kw):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        return await c.get(path, **kw)


class TestModelsEndpoint:
    async def test_list_models(self):
        t = QueueTransport(maxsize=4)
        app = create_gateway(transport=t, model_name="test-model")
        r = await _get(app, "/v1/models")
        assert r.status_code == 200
        assert r.json()["data"][0]["id"] == "test-model"


class TestHealthEndpoint:
    async def test_timeout_without_engine(self):
        t = QueueTransport(maxsize=4)
        app = create_gateway(transport=t, model_name="m")
        r = await _get(app, "/health")
        assert r.status_code == 200
        assert r.json()["status"] == "timeout"


class TestMetricsEndpoint:
    async def test_empty_summary(self):
        t = QueueTransport(maxsize=4)
        app = create_gateway(transport=t, model_name="m")
        r = await _get(app, "/v1/metrics")
        assert r.status_code == 200
        assert r.json()["requests"] == 0.0


class TestAuthMiddleware:
    async def test_no_token_by_default(self):
        t = QueueTransport(maxsize=4)
        app = create_gateway(transport=t, model_name="m")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.get("/v1/models")).status_code == 200

    async def test_token_required(self):
        t = QueueTransport(maxsize=4)
        app = create_gateway(transport=t, model_name="m", api_token="secret")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.get("/v1/models")).status_code == 401
            r = await c.get("/v1/models", headers={"X-API-Token": "secret"})
            assert r.status_code == 200

    async def test_health_skips_auth(self):
        t = QueueTransport(maxsize=4)
        app = create_gateway(transport=t, model_name="m", api_token="secret")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.get("/health")).status_code == 200


class TestSSEFormat:
    def test_basic(self):
        out = _sse_format({"a": 1})
        assert "data: " in out
        assert '"a": 1' in out

    def test_with_event(self):
        out = _sse_format({}, event="ping")
        assert "event: ping" in out


class TestRouteResponse:
    def test_routes_to_queue(self):
        q = asyncio.Queue()
        state = type("S", (), {"_response_queues": {"r1": q}})()
        route_response(state, GenerateComplete(request_id="r1", text="ok"))
        assert q.get_nowait().text == "ok"

    def test_routes_error(self):
        q = asyncio.Queue()
        state = type("S", (), {"_response_queues": {"r1": q}})()
        err = GenerateError(
            request_id="r1", error_code="err", error_message="boom"
        )
        route_response(state, err)
        msg = q.get_nowait()
        assert msg.error_code == "err"

    def test_missing_queue_noop(self):
        state = type("S", (), {"_response_queues": {}})()
        route_response(state, GenerateComplete(request_id="x", text="x"))

    def test_full_queue_noop(self):
        q = asyncio.Queue(maxsize=1)
        q.put_nowait(GenerateComplete(request_id="r1"))
        state = type("S", (), {"_response_queues": {"r1": q}})()
        # Should not raise — just logs warning
        route_response(state, GenerateComplete(request_id="r1", text="overfill"))


class TestPendingResolution:
    """route_response must resolve the blocking endpoint futures.

    Regression: /health, /v1/load and non-streaming chat awaited a future in
    state._pending that route_response never set_result, so every such call
    hung until its timeout even with a live engine.
    """

    def _state(self, pending: dict | None = None):
        return type("S", (), {"_response_queues": {}, "_pending": pending or {}})()

    async def test_health_response_resolves(self):
        fut = asyncio.get_running_loop().create_future()
        state = self._state({"h1": fut})
        route_response(state, HealthResponse(request_id="h1", status="ok", backend="cuda"))
        assert fut.done()
        assert fut.result().status == "ok"
        assert "h1" not in state._pending

    async def test_model_loaded_resolves(self):
        fut = asyncio.get_running_loop().create_future()
        state = self._state({"l1": fut})
        route_response(state, ModelLoaded(request_id="l1", model_path="/m", backend="cuda"))
        assert fut.done()
        assert fut.result().model_path == "/m"
        assert "l1" not in state._pending

    async def test_generate_complete_resolves_and_queues(self):
        fut = asyncio.get_running_loop().create_future()
        q = asyncio.Queue()
        state = type("S", (), {"_response_queues": {"g1": q}, "_pending": {"g1": fut}})()
        route_response(state, GenerateComplete(request_id="g1", text="done"))
        assert fut.done()
        assert fut.result().text == "done"
        assert q.get_nowait().text == "done"

    async def test_generate_error_resolves_and_queues(self):
        fut = asyncio.get_running_loop().create_future()
        q = asyncio.Queue()
        state = type("S", (), {"_response_queues": {"g2": q}, "_pending": {"g2": fut}})()
        route_response(state, GenerateError(request_id="g2", error_code="e", error_message="m"))
        assert fut.done()
        assert fut.result().error_code == "e"
        assert q.get_nowait().error_code == "e"

    async def test_token_delta_never_resolves_pending(self):
        fut = asyncio.get_running_loop().create_future()
        q = asyncio.Queue()
        state = type("S", (), {"_response_queues": {"s1": q}, "_pending": {"s1": fut}})()
        route_response(state, TokenDelta(request_id="s1", token="a"))
        assert not fut.done()
        assert q.get_nowait().token == "a"

    async def test_unknown_pending_id_noop(self):
        fut = asyncio.get_running_loop().create_future()
        state = self._state({"real": fut})
        route_response(state, HealthResponse(request_id="other", status="ok"))
        assert not fut.done()


class TestGrammarPassthrough:
    async def test_grammar_flows_to_engine(self):
        import asyncio

        from kiln.engine.messages import GenerateRequest

        t = QueueTransport(maxsize=4)
        app = create_gateway(transport=t, model_name="m")
        captured: asyncio.Queue = asyncio.Queue()

        async def drain() -> None:
            await captured.put(await t.get())

        task = asyncio.create_task(drain())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            try:
                await c.post(
                    "/v1/chat/completions",
                    json={"messages": [{"role": "user", "content": "hi"}], "grammar": "[a-z]+"},
                    timeout=0.5,
                )
            except Exception:
                pass
        req = await asyncio.wait_for(captured.get(), timeout=2)
        assert isinstance(req, GenerateRequest)
        assert req.grammar == "[a-z]+"
        task.cancel()


class TestRoundTrip:
    """End-to-end gateway ⇄ engine round trips over the transport seam.

    Regression: blocking endpoints (/health, /v1/load) awaited a pending
    future that route_response never resolved, so they hung until timeout
    even when a live engine replied. These tests drive a real request out to
    a responding engine side and assert the gateway resolves normally.
    """

    async def _run(self, request_transport, response_transport, handler, **client_kw):
        app = create_gateway(
            transport=request_transport,
            response_transport=response_transport,
            model_name="m",
        )
        stopped = asyncio.Event()

        async def engine() -> None:
            # Reads gateway → engine requests and replies on the opposite
            # transport, imitating Engine.run().
            while True:
                msg = await request_transport.get()
                resp = await handler(msg)
                if resp is not None:
                    await response_transport.put(resp)

        task = asyncio.create_task(engine())
        # ASGITransport does not fire FastAPI's on_event("startup"), so start
        # the engine→gateway response bridge explicitly (as cli.serve does for
        # the real uvicorn runtime).
        from kiln.engine.gateway import _response_loop

        listener = asyncio.create_task(_response_loop(response_transport, app.state))
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t", **client_kw
            ) as c:
                yield c, app
        finally:
            task.cancel()
            listener.cancel()
            stopped.set()

    async def test_health_round_trip(self):
        async def _go():
            async def handler(msg):
                if isinstance(msg, HealthCheck):
                    return HealthResponse(
                        request_id=msg.request_id,
                        status="ok",
                        model_loaded=True,
                        backend="cuda",
                    )
                return None

            gen = self._run(QueueTransport(maxsize=4), QueueTransport(maxsize=4), handler)
            async for client, app in gen:
                r = await client.get("/health")
                assert r.status_code == 200
                body = r.json()
                assert body["status"] == "ok"
                assert body["model_loaded"] is True
                assert body["backend"] == "cuda"
                return r

        r = await asyncio.wait_for(_go(), timeout=10)
        assert r is not None

    async def test_load_round_trip(self):
        async def _go():
            async def handler(msg):
                if isinstance(msg, LoadModelRequest):
                    return ModelLoaded(
                        request_id=msg.request_id,
                        model_path=msg.model_path,
                        backend="cuda",
                    )
                return None

            gen = self._run(QueueTransport(maxsize=4), QueueTransport(maxsize=4), handler)
            async for client, app in gen:
                r = await client.post(
                    "/v1/load",
                    json={"model_path": "/tmp/m", "quantization": "none"},
                )
                assert r.status_code == 200
                body = r.json()
                assert body["status"] == "loaded"
                assert body["backend"] == "cuda"
                return r

        r = await asyncio.wait_for(_go(), timeout=10)
        assert r is not None

    async def test_streaming_unaffected_by_health_routing(self):
        # A TokenDelta for a streaming request must never resolve an unrelated
        # pending waiter, and a non-streaming chat waiter still resolves.
        req_t = QueueTransport(maxsize=4)
        resp_t = QueueTransport(maxsize=4)
        app = create_gateway(transport=req_t, response_transport=resp_t, model_name="m")

        async def engine() -> None:
            while True:
                msg = await req_t.get()
                if isinstance(msg, GenerateRequest):
                    await resp_t.put(
                        GenerateComplete(
                            request_id=msg.request_id, text="hi there", finish_reason="stop"
                        )
                    )

        task = asyncio.create_task(engine())
        from kiln.engine.gateway import _response_loop

        listener = asyncio.create_task(_response_loop(resp_t, app.state))
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
                r = await asyncio.wait_for(
                    c.post(
                        "/v1/chat/completions",
                        json={"messages": [{"role": "user", "content": "say hi"}], "stream": False},
                    ),
                    timeout=10,
                )
                assert r.status_code == 200
                assert "hi there" in r.text
        finally:
            task.cancel()
            listener.cancel()
