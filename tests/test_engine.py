"""Tests for engine.engine — engine loop and dispatch."""


import pytest

from kiln.engine.engine import Engine
from kiln.engine.messages import (
    GenerateError,
    GenerateRequest,
    HealthCheck,
    HealthResponse,
    QueueTransport,
)


@pytest.fixture
def transports():
    """Create a gateway→engine and engine→gateway transport pair."""
    gw_to_eng = QueueTransport(maxsize=8)
    eng_to_gw = QueueTransport(maxsize=8)
    return gw_to_eng, eng_to_gw


@pytest.fixture
def engine(transports):
    gw_to_eng, eng_to_gw = transports
    return Engine(gateway_transport=gw_to_eng, engine_transport=eng_to_gw)


class TestEngineHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_response(self, engine: Engine, transports):
        """Engine should respond to HealthCheck with HealthResponse."""
        gw_to_eng, eng_to_gw = transports
        req = HealthCheck(request_id="h1")
        await gw_to_eng.put(req)
        # Stop after one message
        engine._running = True
        msg = await gw_to_eng.get()
        await engine._dispatch(msg)
        resp = await eng_to_gw.get()
        assert isinstance(resp, HealthResponse)
        assert resp.request_id == "h1"
        assert resp.status == "ok"
        assert resp.model_loaded is False


class TestEngineGenerateNoModel:
    @pytest.mark.asyncio
    async def test_generate_without_model_returns_error(self, engine: Engine, transports):
        """Should return error when no model is loaded."""
        gw_to_eng, eng_to_gw = transports
        req = GenerateRequest(request_id="g1", model="test")
        await gw_to_eng.put(req)
        msg = await gw_to_eng.get()
        await engine._dispatch(msg)
        resp = await eng_to_gw.get()
        assert isinstance(resp, GenerateError)
        assert resp.error_code == "model_not_loaded"


class TestEngineMessagesToPrompt:
    def test_basic_prompt(self):
        """Should convert messages to a prompt string."""
        from kiln.engine.messages import ChatMessage

        req = GenerateRequest(
            messages=(
                ChatMessage(role="system", content="You are helpful."),
                ChatMessage(role="user", content="Hello!"),
            ),
        )
        prompt = Engine._messages_to_prompt(req)
        assert "<|system|>" in prompt
        assert "You are helpful." in prompt
        assert "<|user|>" in prompt
        assert "Hello!" in prompt
        assert prompt.endswith("<|assistant|>\n")

    def test_assistant_message(self):
        """Should include assistant messages."""
        from kiln.engine.messages import ChatMessage

        req = GenerateRequest(
            messages=(
                ChatMessage(role="user", content="Hi"),
                ChatMessage(role="assistant", content="Hello!"),
                ChatMessage(role="user", content="Bye"),
            ),
        )
        prompt = Engine._messages_to_prompt(req)
        assert "<|assistant|>" in prompt
        assert "Hello!" in prompt
        assert prompt.count("<|assistant|>") == 2  # one from assistant msg, one at end


class _FakeBackend:
    """Minimal backend double recording generated calls."""

    def __init__(self, supports_grammar: bool = False):
        self.supports_grammar = supports_grammar
        self.calls: list[dict] = []

    def generate(self, prompt, *, max_tokens=512, temperature=0.7, top_p=1.0,
                 stop=(), grammar=""):
        self.calls.append({"mode": "sync", "grammar": grammar})
        return "fake response"

    def generate_stream(self, prompt, *, max_tokens=512, temperature=0.7,
                        top_p=1.0, stop=(), grammar=""):
        self.calls.append({"mode": "stream", "grammar": grammar})
        yield "tok", None
        yield "", "length"

    def is_loaded(self):
        return True


class TestEngineGrammar:
    @pytest.mark.asyncio
    async def test_grammar_rejected_when_backend_unsupported(
        self, engine: Engine, transports
    ):
        """Non-empty grammar + backend without supports_grammar -> error."""
        gw_to_eng, eng_to_gw = transports
        from kiln.engine.backends import BackendInfo

        engine._backend = _FakeBackend(supports_grammar=False)
        engine._backend_info = BackendInfo(name="cpu", supports_grammar=False)

        req = GenerateRequest(request_id="g", grammar="^[a-z]+$", stream=True)
        await gw_to_eng.put(req)
        msg = await gw_to_eng.get()
        await engine._dispatch(msg)
        resp = await eng_to_gw.get()
        assert isinstance(resp, GenerateError)
        assert resp.error_code == "grammar_unsupported"
        assert engine._backend.calls == []  # backend never invoked

    @pytest.mark.asyncio
    async def test_grammar_forwarded_to_supporting_backend(
        self, engine: Engine, transports
    ):
        """Grammar is forwarded when the backend claims support."""
        gw_to_eng, eng_to_gw = transports
        from kiln.engine.backends import BackendInfo

        fb = _FakeBackend(supports_grammar=True)
        engine._backend = fb
        engine._backend_info = BackendInfo(name="cuda", supports_grammar=True)

        req = GenerateRequest(request_id="g2", grammar="^[0-9]+$", stream=False)
        await gw_to_eng.put(req)
        msg = await gw_to_eng.get()
        await engine._dispatch(msg)
        resp = await eng_to_gw.get()
        from kiln.engine.messages import GenerateComplete
        assert isinstance(resp, GenerateComplete)
        assert fb.calls and fb.calls[0]["grammar"] == "^[0-9]+$"

    @pytest.mark.asyncio
    async def test_empty_grammar_still_generates(self, engine: Engine, transports):
        """Empty grammar flows to a non-supporting backend unchanged."""
        gw_to_eng, eng_to_gw = transports
        from kiln.engine.backends import BackendInfo

        fb = _FakeBackend(supports_grammar=False)
        engine._backend = fb
        engine._backend_info = BackendInfo(name="cpu", supports_grammar=False)

        req = GenerateRequest(request_id="g3", grammar="", stream=False)
        await gw_to_eng.put(req)
        msg = await gw_to_eng.get()
        await engine._dispatch(msg)
        resp = await eng_to_gw.get()
        from kiln.engine.messages import GenerateComplete
        assert isinstance(resp, GenerateComplete)
        assert fb.calls and fb.calls[0]["grammar"] == ""
