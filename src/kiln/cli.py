"""Kiln CLI — Typer application shell.

Milestone 1: command surface exists as stubs; every command returns a proper
semantic exit code and nothing imports heavy dependencies at module scope.
All command modules are registered eagerly here so the startup-light probe's
single import assertion covers the whole surface.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from kiln._bootstrap import force_utf8_stdio
from kiln.utils import exitcodes
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


@app.command("login")
def login_cmd() -> None:
    """Store your Hugging Face token (needed for gated models)."""
    from kiln.hub.auth import load_token, save_token

    existing = load_token()
    source = "env" if os.environ.get("HF_TOKEN") else "stored"
    if existing:
        console.print(f"A token is already configured (source: {source}).")
    token = typer.prompt("HF token", hide_input=True)
    if not token.strip():
        console.print("[red]Empty token; nothing saved.[/red]")
        raise typer.Exit(exitcodes.USAGE)
    path = save_token(token)
    console.print(f"[green]Token saved to[/green] {path}")


@app.command()
def fetch(
    model: str,
    dest: Annotated[
        Optional[Path],
        typer.Option("--dest", "-d", help="Target directory (default: ./models/<name>)."),
    ] = None,
) -> None:
    """Download a model from the HF hub (resumable, with disk preflight)."""
    from kiln.hub.fetch import fetch_model
    from kiln.utils.errors import map_exception

    target = dest or Path("models") / model.split("/")[-1]
    try:
        fetch_model(model, target)
    except Exception as exc:  # noqa: BLE001 - mapped exit path
        friendly = map_exception(exc)
        console.print(f"[red]{friendly.message}[/red]")
        if friendly.hint:
            console.print(f"[dim]{friendly.hint}[/dim]")
        raise typer.Exit(friendly.exit_code) from exc
    console.print(f"[green]Model ready at[/green] {target}")


data_app = typer.Typer(help="Inspect / lint / preview training data.", no_args_is_help=True)
app.add_typer(data_app, name="data")


@data_app.command("inspect")
def data_inspect(
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
) -> None:
    """Dataset statistics (rows, format, lengths, duplicates)."""
    from kiln.data.stats import inspect_file

    console.print(inspect_file(file).render())


@data_app.command("lint")
def data_lint(
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
) -> None:
    """Validate a dataset; problems are reported with row numbers."""
    from kiln.data.lint import lint_file

    try:
        issues, fmt = lint_file(file)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(exitcodes.USAGE)
    detected = f"detected format: {fmt.value}" if fmt else "format: unrecognized"
    console.print(detected)
    if not issues:
        console.print("[green]OK - no issues found.[/green]")
        return
    for issue in issues:
        style = "red" if issue.rule == "no-loss-target" else "yellow"
        console.print(f"[{style}]{issue.render()}[/{style}]")
    console.print(f"[red]{len(issues)} issue(s) found.[/red]")
    raise typer.Exit(exitcodes.RUNTIME)


@data_app.command("preview")
def data_preview(
    file: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    rows: Annotated[int, typer.Option("--rows", "-n", min=1)] = 3,
) -> None:
    """Render the first N rows as formatted chat."""
    import json as _json

    from rich.panel import Panel

    with open(file, encoding="utf-8") as fh:
        count = 0
        for lineno, line in enumerate(fh, start=1):
            if count >= rows:
                break
            line = line.strip()
            if not line:
                continue
            try:
                row = _json.loads(line)
            except _json.JSONDecodeError:
                break
            body_parts = []
            messages = row.get("messages")
            conversations = row.get("conversations")
            if isinstance(messages, list) and messages:
                for m in messages:
                    body_parts.append(
                        f"[bold]{m.get('role', '?')}:[/bold] {m.get('content', '')}"
                    )
            elif isinstance(conversations, list) and conversations:
                for c in conversations:
                    body_parts.append(
                        f"[bold]{c.get('from', '?')}:[/bold] {c.get('value', '')}"
                    )
            elif "instruction" in row or "output" in row:
                body_parts.append(
                    f"[bold]instruction:[/bold] {row.get('instruction', '')}\n"
                    f"[bold]output:[/bold] {row.get('output', '')}"
                )
            else:
                body_parts.append(_json.dumps(row)[:400])
            console.print(Panel("\n".join(body_parts), title=f"row @ line {lineno}"))
            count += 1


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
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        raise SystemExit(130) from None
    except Exception as exc:  # noqa: BLE001 - single mapped exit path
        friendly = map_exception(exc)
        console.print(f"[red]{friendly.message}[/red]")
        if friendly.hint:
            console.print(f"[dim]{friendly.hint}[/dim]")
        raise SystemExit(friendly.exit_code) from exc


if __name__ == "__main__":
    run()
