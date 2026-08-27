"""Tests for engine.gateway — testable pieces without a running engine."""

import asyncio

from httpx import ASGITransport, AsyncClient

from kiln.engine.gateway import _sse_format, create_gateway, route_response
from kiln.engine.messages import GenerateComplete, GenerateError, QueueTransport


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
