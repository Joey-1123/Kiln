"""Tests for kiln.chat — TUI chat client."""

from __future__ import annotations

from kiln.chat import (
    ChatMessage,
    ChatSession,
    _build_payload,
    _handle_command,
)

# --- ChatMessage ---


class TestChatMessage:
    def test_creation(self) -> None:
        m = ChatMessage(role="user", content="hello")
        assert m.role == "user"
        assert m.content == "hello"


# --- ChatSession ---


class TestChatSession:
    def test_defaults(self) -> None:
        s = ChatSession()
        assert s.messages == []
        assert s.system_prompt == "You are a helpful assistant."
        assert s.server_url == "http://localhost:8080"

    def test_add_user(self) -> None:
        s = ChatSession()
        s.add_user("hi")
        assert len(s.messages) == 1
        assert s.messages[0].role == "user"
        assert s.messages[0].content == "hi"

    def test_add_assistant(self) -> None:
        s = ChatSession()
        s.add_assistant("hello")
        assert len(s.messages) == 1
        assert s.messages[0].role == "assistant"

    def test_clear(self) -> None:
        s = ChatSession()
        s.add_user("a")
        s.add_assistant("b")
        s.clear()
        assert s.messages == []

    def test_to_api_messages_with_system(self) -> None:
        s = ChatSession(system_prompt="You are Kiln.")
        s.add_user("hi")
        msgs = s.to_api_messages()
        assert len(msgs) == 2
        assert msgs[0]["role"] == "system"
        assert msgs[0]["content"] == "You are Kiln."
        assert msgs[1]["role"] == "user"

    def test_to_api_messages_without_system(self) -> None:
        s = ChatSession(system_prompt="")
        s.add_user("hi")
        msgs = s.to_api_messages()
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"


# --- _build_payload ---


class TestBuildPayload:
    def test_streaming_payload(self) -> None:
        s = ChatSession(model_name="llama")
        s.add_user("hi")
        p = _build_payload(s, stream=True)
        assert p["model"] == "llama"
        assert p["stream"] is True
        # system + user = 2 messages
        assert len(p["messages"]) == 2
        assert "temperature" in p

    def test_non_streaming(self) -> None:
        s = ChatSession()
        p = _build_payload(s, stream=False)
        assert p["stream"] is False


# --- _handle_command ---


class TestHandleCommand:
    def test_quit(self) -> None:
        s = ChatSession()
        assert _handle_command(s, "/quit") is False

    def test_exit(self) -> None:
        s = ChatSession()
        assert _handle_command(s, "/exit") is False

    def test_q(self) -> None:
        s = ChatSession()
        assert _handle_command(s, "/q") is False

    def test_clear(self) -> None:
        s = ChatSession()
        s.add_user("msg")
        assert _handle_command(s, "/clear") is True
        assert s.messages == []

    def test_system_set(self) -> None:
        s = ChatSession()
        assert _handle_command(s, "/system Be helpful") is True
        assert s.system_prompt == "Be helpful"

    def test_system_show(self) -> None:
        s = ChatSession()
        # Just verify it doesn't crash
        assert _handle_command(s, "/system") is True

    def test_help(self) -> None:
        s = ChatSession()
        assert _handle_command(s, "/help") is True

    def test_unknown(self) -> None:
        s = ChatSession()
        assert _handle_command(s, "/foo") is True


# --- Health check ---


class TestServerHealthCheck:
    def test_check_server_health_import(self) -> None:
        from kiln.chat import _check_server_health
        assert callable(_check_server_health)
