"""Tests for engine.messages — typed message protocol + transport."""

import asyncio

import pytest

from kiln.engine.messages import (
    ChatMessage,
    GenerateComplete,
    GenerateError,
    GenerateRequest,
    HealthCheck,
    HealthResponse,
    LoadModelRequest,
    ModelLoaded,
    QueueTransport,
    TokenDelta,
    ToolDefinition,
    deserialize,
    serialize,
)


class TestSerialize:
    def test_roundtrip_generate_request(self):
        """GenerateRequest should survive serialize → deserialize."""
        msg = GenerateRequest(
            request_id="abc-123",
            model="test-model",
            messages=(ChatMessage(role="user", content="hello"),),
            temperature=0.5,
            max_tokens=100,
            stream=True,
        )
        data = serialize(msg)
        assert data["__type__"] == "GenerateRequest"
        assert data["request_id"] == "abc-123"
        assert data["model"] == "test-model"
        assert data["temperature"] == 0.5

        restored = deserialize(data)
        assert isinstance(restored, GenerateRequest)
        assert restored.request_id == "abc-123"
        assert restored.model == "test-model"
        assert restored.temperature == 0.5
        assert restored.stream is True

    def test_roundtrip_token_delta(self):
        """TokenDelta should survive roundtrip."""
        msg = TokenDelta(request_id="x", token="hello", finish_reason=None)
        data = serialize(msg)
        restored = deserialize(data)
        assert isinstance(restored, TokenDelta)
        assert restored.token == "hello"
        assert restored.finish_reason is None

    def test_roundtrip_generate_complete(self):
        """GenerateComplete should survive roundtrip."""
        msg = GenerateComplete(
            request_id="x",
            text="done",
            finish_reason="stop",
            usage_prompt_tokens=10,
            usage_completion_tokens=20,
        )
        data = serialize(msg)
        restored = deserialize(data)
        assert isinstance(restored, GenerateComplete)
        assert restored.text == "done"
        assert restored.usage_prompt_tokens == 10

    def test_roundtrip_generate_error(self):
        """GenerateError should survive roundtrip."""
        msg = GenerateError(
            request_id="x",
            error_code="model_not_loaded",
            error_message="No model",
        )
        data = serialize(msg)
        restored = deserialize(data)
        assert isinstance(restored, GenerateError)
        assert restored.error_code == "model_not_loaded"

    def test_roundtrip_health(self):
        """HealthCheck and HealthResponse should survive roundtrip."""
        req = HealthCheck(request_id="h1")
        data = serialize(req)
        restored = deserialize(data)
        assert isinstance(restored, HealthCheck)

        resp = HealthResponse(request_id="h1", status="ok", model_loaded=True, backend="cuda")
        data = serialize(resp)
        restored = deserialize(data)
        assert isinstance(restored, HealthResponse)
        assert restored.model_loaded is True
        assert restored.backend == "cuda"

    def test_roundtrip_load_model(self):
        """LoadModelRequest and ModelLoaded should survive roundtrip."""
        req = LoadModelRequest(request_id="l1", model_path="/models/llama", backend="cuda")
        data = serialize(req)
        restored = deserialize(data)
        assert isinstance(restored, LoadModelRequest)
        assert restored.model_path == "/models/llama"

        resp = ModelLoaded(request_id="l1", model_path="/models/llama", backend="cuda")
        data = serialize(resp)
        restored = deserialize(data)
        assert isinstance(restored, ModelLoaded)
        assert restored.backend == "cuda"


class TestDeserialize:
    def test_missing_type_raises(self):
        """Should raise ValueError on missing __type__."""
        with pytest.raises(ValueError, match="missing"):
            deserialize({"request_id": "x"})

    def test_unknown_type_raises(self):
        """Should raise ValueError on unknown __type__."""
        with pytest.raises(ValueError, match="Unknown message type"):
            deserialize({"__type__": "HackedMessage"})

    def test_injection_guard(self):
        """Should reject client-injected __type__ with unknown value."""
        with pytest.raises(ValueError, match="Unknown message type"):
            deserialize({"__type__": "malicious_type", "request_id": "x"})


class TestChatMessage:
    def test_frozen(self):
        """ChatMessage should be frozen (immutable)."""
        msg = ChatMessage(role="user", content="hi")
        with pytest.raises(AttributeError):
            msg.content = "bye"  # type: ignore[misc]


class TestToolDefinition:
    def test_default_values(self):
        """ToolDefinition should have sensible defaults."""
        t = ToolDefinition()
        assert t.type == "function"
        assert t.function == {}


class TestQueueTransport:
    @pytest.mark.asyncio
    async def test_put_get_roundtrip(self):
        """Should put and get messages in order."""
        transport = QueueTransport(maxsize=8)
        msg1 = GenerateRequest(request_id="1")
        msg2 = GenerateRequest(request_id="2")
        await transport.put(msg1)
        await transport.put(msg2)
        got1 = await transport.get()
        got2 = await transport.get()
        assert got1.request_id == "1"
        assert got2.request_id == "2"

    @pytest.mark.asyncio
    async def test_get_blocks_until_put(self):
        """get() should block until a message is available."""
        transport = QueueTransport(maxsize=4)
        results: list[str] = []

        async def _producer():
            await asyncio.sleep(0.05)
            await transport.put(TokenDelta(request_id="x", token="hi"))

        async def _consumer():
            msg = await transport.get()
            results.append(msg.token)  # type: ignore[union-attr]

        await asyncio.gather(_producer(), _consumer())
        assert results == ["hi"]
