"""MCP stdio server — exposes Kiln operations as MCP tools.

Uses the mcp SDK (v2.x) with MCPServer. All tools are torch-free.
Transport: stdio (V1). Tool table lives here for testability.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import TextContent, ToolAnnotations

SERVER_NAME = "kiln"


def _text(content: str) -> list[TextContent]:
    return [TextContent(type="text", text=content)]


def _json_text(data: Any) -> list[TextContent]:
    return _text(json.dumps(data, indent=2))


def build_server() -> MCPServer:
    server = MCPServer(
        name=SERVER_NAME,
        title="Kiln",
        description="Fine-tune, serve, and chat with open models on consumer hardware.",
        version="0.1.0",
    )

    @server.tool(
        name="kiln_plan",
        description=(
            "Get hardware recommendations for model serving. "
            "Detects GPU, RAM, and disk; recommends backend and quantization."
        ),
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    )
    async def kiln_plan() -> list[TextContent]:
        from kiln.plan import build_plan, format_plan

        result = build_plan()
        return _text(format_plan(result))

    @server.tool(
        name="kiln_doctor",
        description="Check system health: GPU, memory, dependencies, engine binaries.",
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    )
    async def kiln_doctor(
        deep: bool = False,
    ) -> list[TextContent]:
        from kiln.doctor import run_doctor

        report = run_doctor(deep=deep)
        return _json_text(report.to_dict())

    @server.tool(
        name="kiln_fetch",
        description="Download a model from Hugging Face Hub.",
        annotations=ToolAnnotations(openWorldHint=True),
    )
    async def kiln_fetch(
        model_id: str,
        dest: str = "./models",
    ) -> list[TextContent]:
        from kiln.hub.fetch import fetch_model

        result = fetch_model(model_id=model_id, dest=dest)
        return _json_text({
            "status": "ok",
            "model_id": model_id,
            "path": result,
        })

    @server.tool(
        name="kiln_export_gguf",
        description="Export a merged HF model to quantized GGUF for CPU serving.",
        annotations=ToolAnnotations(openWorldHint=False),
    )
    async def kiln_export_gguf(
        model_dir: str,
        output_dir: str = "./gguf",
        quant: str = "Q4_K_M",
    ) -> list[TextContent]:
        from kiln.export import export_gguf

        result = export_gguf(
            model_dir=model_dir,
            output_dir=output_dir,
            quant=quant,
        )
        return _json_text({
            "status": "ok",
            "output_path": result.output_path,
            "quant": result.quant,
            "size_bytes": result.size_bytes,
        })

    @server.tool(
        name="kiln_data_lint",
        description="Lint a training data JSONL file for common issues.",
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    )
    async def kiln_data_lint(
        path: str,
    ) -> list[TextContent]:
        from kiln.data.lint import lint_file

        issues = lint_file(path)
        return _json_text({
            "path": path,
            "issues": [
                {"line": i.line, "rule": i.rule, "message": i.message}
                for i in issues
            ],
            "count": len(issues),
        })

    @server.tool(
        name="kiln_data_stats",
        description="Get statistics for a training data JSONL file.",
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    )
    async def kiln_data_stats(
        path: str,
    ) -> list[TextContent]:
        from kiln.data.stats import compute_stats

        stats = compute_stats(path)
        return _json_text(stats)

    return server


async def run_stdio() -> None:
    """Run the MCP server on stdio transport."""
    server = build_server()
    await server.run_stdio_async()


def main() -> None:
    """Sync entry point for `kiln mcp serve`."""
    import asyncio
    asyncio.run(run_stdio())
