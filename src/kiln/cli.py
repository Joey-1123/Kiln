"""Kiln CLI — Typer application shell.

Milestone 1: command surface exists as stubs; every command returns a proper
semantic exit code and nothing imports heavy dependencies at module scope.
All command modules are registered eagerly here so the startup-light probe's
single import assertion covers the whole surface.
"""

from __future__ import annotations

from typing import Annotated, Optional

import typer
from rich.console import Console

from kiln._bootstrap import force_utf8_stdio
from kiln.utils.errors import map_exception

app = typer.Typer(
    name="kiln",
    help="Fine-tune, serve, and chat with open models on consumer hardware.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
console = Console()

# Stubs that arrive in later milestones, listed for --help discoverability.
_NOT_IMPLEMENTED = {
    "init": "Milestone 1 (wizard lands with config templates)",
    "fetch": "Milestone 2",
    "data": "Milestone 2",
    "train": "Milestone 3",
    "serve": "Milestone 4",
    "chat": "Milestone 6",
    "export": "Milestone 5",
}


def _stub_exit(command: str) -> None:
    console.print(f"[yellow]'{command}' is not implemented yet.[/yellow]")
    raise typer.Exit(code=1)


@app.command()
def version() -> None:
    """Print the Kiln version."""
    from kiln import __version__

    console.print(f"kiln {__version__}")


@app.command()
def init(
    template: Annotated[
        Optional[str], typer.Option(help="Start from a template (e.g. chat).")
    ] = None,
) -> None:
    """Create a new kiln.yaml config."""
    _stub_exit("init")


@app.command()
def fetch(model: str) -> None:
    """Download a model from the HF hub."""
    _stub_exit("fetch")


@app.command("data")
def data_cmd() -> None:
    """Inspect / lint / preview training data."""
    _stub_exit("data")


@app.command()
def train(
    config: Annotated[Optional[str], typer.Option("--config", "-c")] = None,
) -> None:
    """Fine-tune a model (SFT/DPO via QLoRA)."""
    _stub_exit("train")


@app.command()
def serve(
    model: Annotated[Optional[str], typer.Option("--model", "-m")] = None,
) -> None:
    """Start the OpenAI/Anthropic-compatible API server."""
    _stub_exit("serve")


@app.command()
def chat(model: Annotated[Optional[str], typer.Option("--model", "-m")] = None) -> None:
    """Chat with a model interactively."""
    _stub_exit("chat")


@app.command()
def doctor() -> None:
    """Check GPU / memory / deps / environment readiness."""
    _stub_exit("doctor")


@app.command()
def plan() -> None:
    """Show what this machine can run before downloading anything."""
    _stub_exit("plan")


@app.command()
def ship(config: Annotated[Optional[str], typer.Option("--config", "-c")] = None) -> None:
    """Run the eval gate; exit code carries the SHIP/DON'T-SHIP verdict."""
    _stub_exit("ship")


@app.command()
def export(
    model: str,
    format: Annotated[str, typer.Option("--format", "-f")] = "gguf",
) -> None:
    """Export a model/adapter to another format."""
    _stub_exit("export")


def run() -> None:
    """Console-script entry point: bootstrap, then run the app."""
    force_utf8_stdio()
    try:
        app()
    except Exception as exc:  # noqa: BLE001 - single mapped exit path
        friendly = map_exception(exc)
        console.print(f"[red]{friendly.message}[/red]")
        if friendly.hint:
            console.print(f"[dim]{friendly.hint}[/dim]")
        raise SystemExit(friendly.exit_code) from exc


if __name__ == "__main__":
    run()
