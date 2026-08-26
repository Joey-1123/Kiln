"""Kiln TUI chat — interactive chat with models via the gateway.

Two modes:
  1. Client mode (default): connects to a running `kiln serve` instance
  2. Standalone mode (--model): starts engine locally, serves, and chats

Uses prompt_toolkit for line editing (history, completion, Vi/Emacs bindings).
Streams responses token-by-token via SSE from the OpenAI-compatible endpoint.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from typing import Any

import httpx
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

_SYSTEM_PROMPT_DEFAULT = "You are a helpful assistant."


@dataclass
class ChatMessage:
    """A single chat message (role + content)."""
    role: str
    content: str


@dataclass
class ChatSession:
    """Holds chat history, system prompt, and server config for a chat session."""
    messages: list[ChatMessage] = field(default_factory=list)
    system_prompt: str = _SYSTEM_PROMPT_DEFAULT
    server_url: str = "http://localhost:8080"
    model_name: str = "default"

    def add_user(self, content: str) -> None:
        """Append a user message to the conversation."""
        self.messages.append(ChatMessage(role="user", content=content))

    def add_assistant(self, content: str) -> None:
        """Append an assistant message to the conversation."""
        self.messages.append(ChatMessage(role="assistant", content=content))

    def clear(self) -> None:
        """Reset the conversation history."""
        self.messages.clear()

    def to_api_messages(self) -> list[dict[str, str]]:
        """Render the session as OpenAI-style message dicts."""
        result = []
        if self.system_prompt:
            result.append({"role": "system", "content": self.system_prompt})
        for m in self.messages:
            result.append({"role": m.role, "content": m.content})
        return result


def _build_payload(session: ChatSession, stream: bool = True) -> dict[str, Any]:
    return {
        "model": session.model_name,
        "messages": session.to_api_messages(),
        "stream": stream,
        "temperature": 0.7,
        "max_tokens": 2048,
    }


async def _stream_response(
    client: httpx.AsyncClient,
    session: ChatSession,
) -> str:
    """POST to /v1/chat/completions with SSE streaming, print tokens live."""
    payload = _build_payload(session, stream=True)
    full_response = []

    try:
        async with client.stream(
            "POST",
            "/v1/chat/completions",
            json=payload,
            timeout=httpx.Timeout(60.0, connect=10.0),
        ) as resp:
            if resp.status_code != 200:
                body = await resp.aread()
                console.print(f"[red]Server error ({resp.status_code}):[/red]")
                try:
                    err = json.loads(body)
                    console.print(err.get("detail", body.decode()))
                except Exception:
                    console.print(body.decode()[:500])
                return ""

            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    token = delta.get("content")
                    if token:
                        full_response.append(token)
                        sys.stdout.write(token)
                        sys.stdout.flush()
                except json.JSONDecodeError:
                    continue

    except httpx.ConnectError:
        console.print(
            f"[red]Cannot connect to {session.server_url}.[/red]\n"
            "[dim]Is `kiln serve` running? Start it with: kiln serve --model <path>[/dim]"
        )
        return ""
    except httpx.TimeoutException:
        console.print("[red]Request timed out.[/red]")
        return ""
    except KeyboardInterrupt:
        console.print("\n[dim]Generation cancelled.[/dim]")
        return "".join(full_response)

    sys.stdout.write("\n")
    sys.stdout.flush()
    return "".join(full_response)


def _print_help() -> None:
    help_text = Text()
    help_text.append("Commands:\n", style="bold")
    help_text.append("  /quit, /exit    ", style="cyan")
    help_text.append("Exit chat\n")
    help_text.append("  /clear          ", style="cyan")
    help_text.append("Reset conversation history\n")
    help_text.append("  /system <text>  ", style="cyan")
    help_text.append("Set system prompt\n")
    help_text.append("  /system          ", style="cyan")
    help_text.append("Show current system prompt\n")
    help_text.append("  /history         ", style="cyan")
    help_text.append("Show conversation history\n")
    help_text.append("  /help            ", style="cyan")
    help_text.append("Show this help\n")
    console.print(Panel(help_text, title="Chat Commands"))


def _print_history(session: ChatSession) -> None:
    if not session.messages:
        console.print("[dim]No messages yet.[/dim]")
        return
    for msg in session.messages:
        if msg.role == "user":
            console.print(f"\n[bold blue]You:[/bold blue] {msg.content}")
        else:
            console.print(f"\n[bold green]Assistant:[/bold green] {msg.content}")


def _handle_command(session: ChatSession, user_input: str) -> bool:
    """Handle slash commands. Returns True if chat should continue."""
    parts = user_input.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd in ("/quit", "/exit", "/q"):
        return False

    if cmd == "/clear":
        session.clear()
        console.print("[dim]Conversation cleared.[/dim]")
        return True

    if cmd == "/system":
        if arg:
            session.system_prompt = arg
            console.print("[dim]System prompt set.[/dim]")
        else:
            console.print(f"[dim]Current system prompt:[/dim] {session.system_prompt}")
        return True

    if cmd == "/history":
        _print_history(session)
        return True

    if cmd == "/help":
        _print_help()
        return True

    console.print(f"[yellow]Unknown command: {cmd}[/yellow]. Type /help for available commands.")
    return True


async def _chat_loop(
    session: ChatSession,
    client: httpx.AsyncClient,
) -> None:
    """Main async chat loop with prompt_toolkit."""
    prompt_session = PromptSession(
        history=InMemoryHistory(),
        message=lambda: [("You: ", "")],
        multiline=False,
    )

    while True:
        try:
            user_input = await prompt_session.prompt_async()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Goodbye![/dim]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        if user_input.startswith("/"):
            should_continue = _handle_command(session, user_input)
            if not should_continue:
                break
            continue

        session.add_user(user_input)

        response = await _stream_response(client, session)
        if response:
            session.add_assistant(response)


def _check_server_health(server_url: str) -> bool:
    """Quick health check against a running server."""
    try:
        resp = httpx.get(f"{server_url}/health", timeout=5.0)
        return resp.status_code == 200
    except Exception:
        return False


def run_chat(
    server_url: str = "http://localhost:8080",
    model: str | None = None,
) -> None:
    """Entry point for `kiln chat`."""
    console.print(
        Panel(
            f"Server: [bold]{server_url}[/bold]\n"
            f"Model:  [bold]{model or 'default'}[/bold]\n"
            f"Type [bold]/help[/] for commands, [bold]/quit[/] to exit.",
            title="[bold]Kiln Chat[/bold]",
            border_style="blue",
        )
    )

    if not _check_server_health(server_url):
        console.print(
            f"[yellow]Warning: cannot reach server at {server_url}[/yellow]\n"
            "[dim]The server may not be started yet. Responses will fail until it's running.[/dim]"
        )

    session = ChatSession(
        server_url=server_url,
        model_name=model or "default",
    )

    client = httpx.AsyncClient(base_url=server_url)

    try:
        asyncio.run(_chat_loop(session, client))
    except KeyboardInterrupt:
        console.print("\n[dim]Goodbye![/dim]")
    finally:
        asyncio.run(client.aclose())
