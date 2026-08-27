"""Kiln CLI — Typer application shell.

All command modules are registered eagerly here so the startup-light probe's
single import assertion covers the whole surface.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Annotated, Any, Optional

import typer
from rich.console import Console

from kiln._bootstrap import force_utf8_stdio
from kiln.utils import exitcodes
from kiln.utils.errors import map_exception


def _version_callback(
    version: bool = typer.Option(False, "--version", help="Show version and exit."),
) -> None:
    if version:
        from kiln import __version__

        console.print(f"kiln {__version__}")
        raise typer.Exit(exitcodes.OK)


app = typer.Typer(
    name="kiln",
    help="Fine-tune, serve, and chat with open models on consumer hardware.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
    callback=_version_callback,
    invoke_without_command=True,
)
console = Console()
console_err = Console(stderr=True)

# Stubs that arrive in later milestones, listed for --help discoverability.
# (All V1 commands are now implemented; this map is empty but kept so future
# deferred commands remain discoverable in --help without being invokable.)
_NOT_IMPLEMENTED: dict[str, str] = {}


@app.command()
def version() -> None:
    """Print the Kiln version."""
    from kiln import __version__

    console.print(f"kiln {__version__}")


@app.command()
def init(
    template: Annotated[
        Optional[str],
        typer.Option(
            "--template", "-t", help="Config template: chat | train | serve (default: chat)."
        ),
    ] = "chat",
    model: Annotated[
        Optional[str],
        typer.Option("--model", "-m", help="Base model HF repo id or local path."),
    ] = None,
    data: Annotated[
        Optional[Path],
        typer.Option("--data", "-d", help="Training data file (required for the train template)."),
    ] = None,
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Output kiln.yaml path (default: ./kiln.yaml)."),
    ] = Path("kiln.yaml"),
    force: Annotated[
        bool, typer.Option("--force", "-f", help="Overwrite an existing config file.")
    ] = False,
) -> None:
    """Create a new kiln.yaml config from a template.

    Interactive by default (prompts for any missing value); pass ``--model`` /
    ``--data`` for non-interactive / CI use.
    """
    from kiln.config.schema import (
        DataConfig,
        KilnConfig,
        ModelConfig,
        RecipeConfig,
        config_to_yaml,
    )

    template = (template or "chat").lower()
    if template not in {"chat", "train", "serve"}:
        console.print(f"[red]Unknown template {template!r}; expected chat|train|serve.[/red]")
        raise typer.Exit(exitcodes.USAGE)

    if model is None:
        if not force and not typer.get_text_stream("stdin").isatty():
            console.print("[red]--model is required in non-interactive mode.[/red]")
            raise typer.Exit(exitcodes.USAGE)
        model = typer.prompt("Base model (HF repo id or local path)")

    if not model or not model.strip():
        console.print("[red]Empty model; nothing written.[/red]")
        raise typer.Exit(exitcodes.USAGE)

    if template == "train":
        data_path = data or Path("data/train.jsonl")
        recipe = RecipeConfig(
            model=ModelConfig(base=model.strip()),
            data=DataConfig(train=data_path),
        )
    else:
        recipe = RecipeConfig(model=ModelConfig(base=model.strip()))

    if config.exists() and not force:
        console.print(f"[red]{config} already exists; pass --force to overwrite.[/red]")
        raise typer.Exit(exitcodes.USAGE)

    cfg = KilnConfig(recipe=recipe)
    config.write_text(config_to_yaml(cfg), encoding="utf-8")
    console.print(
        f"[green]Wrote {template} config to[/green] {config}\n"
        f"[dim]Edit it, then run: kiln fetch {model}  ·  "
        f"{'kiln train' if template == 'train' else 'kiln serve'}[/dim]"
    )


@app.command("login")
def login_cmd(
    token: Annotated[
        Optional[str],
        typer.Option("--token", help="HF token (non-interactive/CI mode)."),
    ] = None,
) -> None:
    """Store your Hugging Face token (needed for gated models)."""
    from kiln.hub.auth import load_token, save_token

    existing = load_token()
    source = "env" if os.environ.get("HF_TOKEN") else "stored"
    if existing and not token:
        console.print(f"A token is already configured (source: {source}).")
    if not token:
        token = typer.prompt("HF token", hide_input=True)
    if not token.strip():
        console.print("[red]Empty token; nothing saved.[/red]")
        raise typer.Exit(exitcodes.USAGE)
        path = save_token(token)
        console.print(f"[green]Token saved to[/green] {path}")


@app.command()
def tune(
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Re-measure even if a valid cached calibration exists."),
    ] = False,
) -> None:
    """Self-calibrate this machine's bandwidth and recommend a backend strategy.

    Writes a GPU-UUID (or stable host-fingerprint) keyed measurement into the
    cache consumed by `plan` for prod backend selection (plan A10). Stale
    entries are disqualified by timestamp.
    """
    from kiln.tune.cache import MeasurementCache, host_uuid
    from kiln.tune.measure import measure_bandwidth_gbps, recommend

    key = host_uuid()
    cache = MeasurementCache()
    cached = cache.load(key)
    if not force and cache.is_valid(cached):
        bw = cached.get("bandwidth_gbps")
        rec = cached.get("recommendation") or recommend(bw)
        console.print(f"[green]Using cached calibration for[/green] {key}")
        console.print(f"  bandwidth: {bw} GB/s" if bw is not None else "  bandwidth: (none)")
        console.print(f"  recommendation: {rec}")
        return

    bw = measure_bandwidth_gbps()
    rec = recommend(bw)
    cache.save(
        key,
        {
            "measured_at": int(time.time()),
            "bandwidth_gbps": bw,
            "recommendation": rec,
            "torch_available": bw is not None,
        },
    )
    if bw is None:
        console.print(
            "[yellow]No CUDA/torch available; stored a conservative 'cpu' recommendation.[/yellow]"
        )
        console.print("[dim]Install the [train] extras to enable bandwidth measurement.[/dim]")
    else:
        console.print(f"[green]Measured[/green] {bw:.1f} GB/s -> recommendation: {rec}")


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
    config: Annotated[str, typer.Option("--config", "-c", help="Path to kiln.yaml")],
    mode: Annotated[str, typer.Option("--mode", "-m", help="sft or dpo")] = "sft",
) -> None:
    """Fine-tune a model (SFT/DPO via QLoRA)."""
    from kiln.config.config_sha import recipe_hash
    from kiln.config.schema import load_config
    from kiln.tracking.runs import RunTracker

    try:
        cfg = load_config(config)
    except Exception as exc:
        friendly = map_exception(exc)
        console.print(f"[red]{friendly.message}[/red]")
        if friendly.hint:
            console.print(f"[dim]{friendly.hint}[/dim]")
        raise typer.Exit(friendly.exit_code)

    sha = recipe_hash(cfg)
    tracker = RunTracker(Path(cfg.recipe.output.dir) / "runs.db")
    run_record = tracker.start_run(
        config_sha=sha,
        model=cfg.recipe.model.base,
        mode=mode,
    )
    console.print(f"[dim]Run #{run_record.id} started (sha={sha}, mode={mode})[/dim]")

    if mode == "sft":
        from kiln.trainer.sft import train_sft

        result = train_sft(
            model_path=cfg.recipe.model.base,
            dataset_path=str(cfg.recipe.data.train) if cfg.recipe.data else "",
            output_dir=str(cfg.recipe.output.dir),
            config=cfg.model_dump(mode="json"),
            lora_rank=cfg.recipe.training.lora.r,
            lora_alpha=cfg.recipe.training.lora.alpha,
            lora_dropout=cfg.recipe.training.lora.dropout,
            batch_size=(
                cfg.recipe.training.batch_size
                if isinstance(cfg.recipe.training.batch_size, int) else 4
            ),
            epochs=cfg.recipe.training.epochs,
            lr=cfg.recipe.training.lr,
            seed=cfg.recipe.training.seed,
            quantization=cfg.recipe.training.quantization,
        )
    elif mode == "dpo":
        from kiln.trainer.dpo import train_dpo

        result = train_dpo(
            model_path=cfg.recipe.model.base,
            dataset_path=str(cfg.recipe.data.train) if cfg.recipe.data else "",
            output_dir=str(cfg.recipe.output.dir),
            config=cfg.model_dump(mode="json"),
            lora_rank=cfg.recipe.training.lora.r,
            lora_alpha=cfg.recipe.training.lora.alpha,
            lora_dropout=cfg.recipe.training.lora.dropout,
            batch_size=(
                cfg.recipe.training.batch_size
                if isinstance(cfg.recipe.training.batch_size, int) else 2
            ),
            epochs=cfg.recipe.training.epochs,
            lr=cfg.recipe.training.lr,
            seed=cfg.recipe.training.seed,
            quantization=cfg.recipe.training.quantization,
        )
    else:
        console.print(f"[red]Unknown mode: {mode!r}. Use 'sft' or 'dpo'.[/red]")
        raise typer.Exit(exitcodes.USAGE)

    if result.success:
        tracker.finish_run(
            run_record.id,
            status="completed",
            adapter_path=result.adapter_path,
        )
        console.print(f"[green]Training complete.[/green] Adapter: {result.adapter_path}")
    else:
        tracker.finish_run(run_record.id, status="failed", notes=result.error)
        console.print(f"[red]Training failed: {result.error}[/red]")
        raise typer.Exit(exitcodes.RUNTIME)


@app.command()
def serve(
    model: Annotated[Optional[str], typer.Option("--model", "-m")] = None,
    config: Annotated[Optional[str], typer.Option("--config", "-c")] = None,
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8000,
    supervisor: Annotated[
        bool, typer.Option("--supervisor/--no-supervisor")
    ] = False,
) -> None:
    """Start the OpenAI/Anthropic-compatible API server."""
    import asyncio
    import sys

    import uvicorn

    from kiln.engine.backends.cuda_native import register as register_cuda
    from kiln.engine.backends.llama_cpp import register as register_cpu
    from kiln.engine.engine import Engine
    from kiln.engine.gateway import create_gateway
    from kiln.engine.messages import QueueTransport

    # Register backends (never imports torch/llama_cpp)
    register_cuda()
    register_cpu()

    model_name = model or "default"

    # Load config for serve settings if provided
    api_token = None
    if config:
        try:
            from kiln.config.schema import load_config
            cfg = load_config(config)
            host = cfg.recipe.serve.host
            port = cfg.recipe.serve.port
        except Exception as exc:
            console.print(f"[yellow]Warning: could not load config: {exc}[/yellow]")

    # If supervisor mode, start engine as a separate process
    if supervisor:
        from kiln.engine.supervisor import run_supervisor
        console.print("[dim]Starting in supervisor mode...[/dim]")
        engine_cmd = [sys.executable, "-m", "kiln.engine.engine"]
        run_supervisor(engine_cmd)
        return

    # Single-process mode: gateway + engine fused (A1 amendment)
    engine_out = QueueTransport()  # engine → gateway
    gw_out = QueueTransport()  # gateway → engine

    engine = Engine(gateway_transport=gw_out, engine_transport=engine_out)
    gw_transport = QueueTransport()  # gateway HTTP → engine

    app = create_gateway(
        transport=gw_transport,
        model_name=model_name,
        api_token=api_token,
        response_transport=engine_out,
    )

    console.print(f"[green]Kiln server starting on {host}:{port}[/green]")
    console.print(f"[dim]Docs: http://{host}:{port}/docs[/dim]")
    console.print("[dim]Press Ctrl-C to stop.[/dim]")

    config_uvicorn = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config_uvicorn)

    async def _run_all() -> None:
        engine_task = asyncio.create_task(engine.run())
        try:
            await server.serve()
        finally:
            engine.stop()
            engine_task.cancel()

    asyncio.run(_run_all())


@app.command()
def chat(
    model: Annotated[Optional[str], typer.Option("--model", "-m")] = None,
    server: Annotated[
        str, typer.Option("--server", help="Server URL to connect to.")
    ] = "http://localhost:8080",
) -> None:
    """Chat with a model interactively via the running server."""
    from kiln.chat import run_chat

    run_chat(server_url=server, model=model)


mcp_app = typer.Typer(help="MCP server commands.", no_args_is_help=True)
app.add_typer(mcp_app, name="mcp")


@mcp_app.command("serve")
def mcp_serve() -> None:
    """Start the Kiln MCP server on stdio transport."""
    from kiln.mcp_server import run_stdio

    asyncio.run(run_stdio())


env_app = typer.Typer(help="Environment variable inventory.", no_args_is_help=True)
app.add_typer(env_app, name="env")


@env_app.command("scan")
def env_scan(
    path: Annotated[
        str, typer.Argument(help="Directory or file to scan.")
    ] = "src/kiln",
    output: Annotated[
        Optional[str],
        typer.Option("--output", "-o", help="Write manifest JSON to this path."),
    ] = None,
    include_tests: Annotated[
        bool, typer.Option("--include-tests", help="Include tests/ directory.")
    ] = False,
) -> None:
    """Scan Python files for env var usage (os.environ, os.getenv, etc.)."""
    from kiln.env_inventory import scan_directory, scan_file, write_manifest

    target = Path(path)
    if target.is_file():
        from kiln.env_inventory import EnvInventory
        usages = scan_file(str(target))
        inventory = EnvInventory(
            variables=usages,
            source_root=str(target),
            file_count=1,
        )
    elif target.is_dir():
        inventory = scan_directory(
            str(target),
            include_tests=include_tests,
        )
    else:
        console.print(f"[red]Path not found: {path}[/red]")
        raise typer.Exit(exitcodes.USAGE)

    console.print(
        f"[dim]Scanned {inventory.file_count} files, "
        f"found {len(inventory.variables)} env var usages "
        f"across {len(inventory.unique_vars())} unique variables.[/dim]"
    )

    if output:
        write_manifest(inventory, output)
        console.print(f"[green]Manifest written to {output}[/green]")
    else:
        # Pretty print to console
        for name, info in sorted(inventory.unique_vars().items()):
            default_str = f" (default={info['default']})" if info.get("default") else ""
            console.print(f"  {name}{default_str}")
            for src in info["sources"]:
                console.print(f"    {src['file']}:{src['line']} [{src['accessor']}]")


@env_app.command("drift")
def env_drift(
    manifest: Annotated[str, typer.Argument(help="Path to manifest JSON file.")],
    path: Annotated[
        str, typer.Option("--path", help="Directory to scan.")
    ] = "src/kiln",
) -> None:
    """Compare a saved manifest against current env var usage."""
    from kiln.env_inventory import detect_drift, scan_directory

    inventory = scan_directory(path)
    result = detect_drift(manifest, inventory)

    if result["status"] == "error":
        console.print(f"[red]{result['message']}[/red]")
        raise typer.Exit(exitcodes.RUNTIME)

    if not result["drifted"]:
        console.print(
            f"[green]No drift detected.[/green] "
            f"Manifest has {result['old_count']} vars, codebase has {result['new_count']}."
        )
        return

    console.print("[yellow]Drift detected![/yellow]")
    console.print(f"  Old manifest: {result['old_count']} vars")
    console.print(f"  Current:      {result['new_count']} vars")
    if result["added"]:
        console.print(f"  [green]Added:[/green] {', '.join(result['added'])}")
    if result["removed"]:
        console.print(f"  [red]Removed:[/red] {', '.join(result['removed'])}")
    raise typer.Exit(exitcodes.VERDICT_FAIL)


@app.command()
def doctor(
    deep: Annotated[
        bool, typer.Option("--deep", help="Full validation including engine binaries.")
    ] = False,
    json_output: Annotated[
        bool, typer.Option("--json", help="Structured JSON output.")
    ] = False,
) -> None:
    """Check GPU / memory / deps / environment readiness."""
    from kiln.doctor import run_doctor

    report = run_doctor(deep=deep)

    if json_output:
        import json as json_mod
        console.print(json_mod.dumps(report.to_dict(), indent=2))
    else:
        _print_doctor_report(report)

    if report.status == "fail":
        raise typer.Exit(exitcodes.RUNTIME)
    raise typer.Exit(exitcodes.OK)


def _print_doctor_report(report: Any) -> None:
    from rich.panel import Panel
    from rich.table import Table

    status_color = {"pass": "green", "warn": "yellow", "fail": "red"}.get(
        report.status, "dim"
    )
    console.print(
        Panel(
            f"Status: [{status_color}]{report.status.upper()}[/]",
            title="Kiln Doctor",
        )
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("Check")
    table.add_column("Status", justify="center")
    table.add_column("Summary")

    for check in report.checks:
        color = {"pass": "green", "warn": "yellow", "fail": "red", "skip": "dim"}.get(
            check.status, "dim"
        )
        table.add_row(
            check.id,
            f"[{color}]{check.status.upper()}[/]",
            check.summary,
        )

    console.print(table)

    fails = [c for c in report.checks if c.status == "fail"]
    if fails:
        console.print(f"\n[red]{len(fails)} issue(s) found.[/]")


@app.command()
def plan(
    json_output: Annotated[
        bool, typer.Option("--json", help="Structured JSON output.")
    ] = False,
    write_config: Annotated[
        Optional[str],
        typer.Option("--write-config", help="Write suggested config to this path."),
    ] = None,
) -> None:
    """Show what this machine can run before downloading anything."""
    from kiln.plan import build_plan, format_plan

    result = build_plan()

    if json_output:
        import json as json_mod
        console.print(json_mod.dumps(result.to_dict(), indent=2))
    else:
        console.print(format_plan(result))

    if write_config:
        import yaml

        cfg_path = Path(write_config)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)

        existing: dict = {}
        if cfg_path.is_file():
            with open(cfg_path) as f:
                existing = yaml.safe_load(f) or {}

        existing.setdefault("serving", {})
        existing["serving"]["backend"] = result.backend
        existing["serving"]["quantization"] = result.quant_recommendation

        with open(cfg_path, "w") as f:
            yaml.dump(existing, f, default_flow_style=False)

        console.print(f"\n[green]Config written to {cfg_path}[/green]")


@app.command()
def ship(
    config: Annotated[str, typer.Option("--config", "-c", help="Path to kiln.yaml")],
    metric: Annotated[str, typer.Option("--metric", help="Metric name to evaluate")] = "accuracy",
    value: Annotated[float, typer.Option("--value", help="Measured metric value")] = 0.0,
) -> None:
    """Run the eval gate; exit code carries the SHIP/DON'T-SHIP verdict."""
    from kiln.config.config_sha import recipe_hash
    from kiln.config.schema import load_config
    from kiln.utils.ship_verdict import judge

    try:
        cfg = load_config(config)
    except Exception as exc:
        friendly = map_exception(exc)
        console.print(f"[red]{friendly.message}[/red]")
        if friendly.hint:
            console.print(f"[dim]{friendly.hint}[/dim]")
        raise typer.Exit(friendly.exit_code)

    threshold = cfg.eval.ship.metric_threshold
    verdict = judge(
        metric_name=metric,
        metric_value=value,
        threshold=threshold,
    )

    sha = recipe_hash(cfg)
    console.print(f"[dim]config_sha={sha}[/dim]")
    console.print(f"[dim]{verdict.reason}[/dim]")

    if verdict.is_ship:
        console.print("[green]SHIP[/green]")
        raise typer.Exit(exitcodes.OK)
    else:
        console.print("[red]DON'T-SHIP[/red]")
        raise typer.Exit(exitcodes.VERDICT_FAIL)


@app.command()
def merge(
    adapter: Annotated[
        str, typer.Option("--adapter", "-a", help="Path to LoRA adapter dir")
    ],
    output: Annotated[
        str, typer.Option("--output", "-o", help="Output path for merged model")
    ],
    base_model: Annotated[
        Optional[str],
        typer.Option(
            "--base-model",
            help="Base model (auto-detected from adapter config if omitted)",
        ),
    ] = None,
) -> None:
    """Merge a LoRA adapter into the base model and save as safetensors."""
    from pathlib import Path

    adapter_path = Path(adapter)
    if not adapter_path.is_dir():
        console.print(f"[red]Adapter directory not found: {adapter_path}[/red]")
        raise typer.Exit(exitcodes.USAGE)

    try:
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        # Auto-detect base model from adapter config if not provided
        if base_model is None:
            adapter_config_path = adapter_path / "adapter_config.json"
            if not adapter_config_path.exists():
                console.print(
                    "[red]Cannot auto-detect base model: "
                    "adapter_config.json not found.[/red]"
                )
                raise typer.Exit(exitcodes.USAGE)
            import json
            with open(adapter_config_path) as f:
                adapter_cfg = json.load(f)
            base_model = adapter_cfg.get("base_model_name_or_path")
            if not base_model:
                console.print("[red]base_model_name_or_path not in adapter_config.json.[/red]")
                raise typer.Exit(exitcodes.USAGE)

        console.print(f"[dim]Loading base model: {base_model}[/dim]")
        model = AutoModelForCausalLM.from_pretrained(base_model, device_map="auto")
        tokenizer = AutoTokenizer.from_pretrained(base_model)

        console.print(f"[dim]Loading adapter: {adapter_path}[/dim]")
        model = PeftModel.from_pretrained(model, str(adapter_path))

        console.print("[dim]Merging weights...[/dim]")
        model = model.merge_and_unload()

        console.print(f"[dim]Saving to {output}...[/dim]")
        output_path = Path(output)
        output_path.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(str(output_path))
        tokenizer.save_pretrained(str(output_path))

        console.print(f"[green]Merged model saved to {output_path}[/green]")
    except ImportError:
        console.print(
            '[red]Merge requires peft and transformers. '
            'Install with: pip install "kiln-cli[train]"[/red]'
        )
        raise typer.Exit(exitcodes.RUNTIME)
    except Exception as exc:
        friendly = map_exception(exc)
        console.print(f"[red]{friendly.message}[/red]")
        if friendly.hint:
            console.print(f"[dim]{friendly.hint}[/dim]")
        raise typer.Exit(friendly.exit_code)


@app.command()
def export_gguf(
    model_dir: Annotated[str, typer.Argument(help="Path to merged HF model directory")],
    output_dir: Annotated[str, typer.Option("--output-dir", "-o")] = "./gguf",
    quant: Annotated[str, typer.Option("--quant", "-q")] = "Q4_K_M",
    llama_cpp_dir: Annotated[
        Optional[str],
        typer.Option("--llama-cpp-dir", help="Path to llama.cpp (auto-downloaded if omitted)."),
    ] = None,
) -> None:
    """Export a merged HF model to quantized GGUF for CPU serving."""
    from kiln.export import export_gguf as do_export
    from kiln.export import list_quantizations

    if quant not in list_quantizations():
        console.print(
            f"[red]Unknown quantization {quant!r}. "
            f"Available: {', '.join(list_quantizations())}[/red]"
        )
        raise typer.Exit(exitcodes.USAGE)

    try:
        result = do_export(
            model_dir=model_dir,
            output_dir=output_dir,
            quant=quant,
            llama_cpp_dir=llama_cpp_dir,
        )
        size_mb = result.size_bytes / (1024 * 1024)
        console.print(
            f"[green]Exported {result.quant} GGUF:[/green] "
            f"{result.output_path} ({size_mb:.1f} MB)"
        )
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(exitcodes.USAGE)
    except Exception as exc:
        friendly = map_exception(exc)
        console.print(f"[red]{friendly.message}[/red]")
        if friendly.hint:
            console.print(f"[dim]{friendly.hint}[/dim]")
        raise typer.Exit(friendly.exit_code)


def run() -> None:
    """Console-script entry point: bootstrap, then run the app."""
    force_utf8_stdio()
    try:
        app()
    except KeyboardInterrupt:
        console_err.print("\n[yellow]Interrupted.[/yellow]")
        raise SystemExit(130) from None
    except Exception as exc:  # noqa: BLE001 - single mapped exit path
        friendly = map_exception(exc)
        console_err.print(f"[red]{friendly.message}[/red]")
        if friendly.hint:
            console_err.print(f"[dim]{friendly.hint}[/dim]")
        raise SystemExit(friendly.exit_code) from exc


if __name__ == "__main__":
    run()
