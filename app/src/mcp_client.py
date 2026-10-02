"""Stdio MCP client shared by the hand-check script and, later, the planner and reflector."""

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

SERVER_PATH = Path(__file__).resolve().parent / "server.py"


def list_tools() -> list[str]:
    """Launch the IT server and return the registered tool names."""
    return anyio.run(_list_tools)


def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Launch the IT server, call one tool, and return its JSON result."""
    return anyio.run(_call_tool, name, arguments)


async def _list_tools() -> list[str]:
    async with _session() as session:
        listed = await session.list_tools()
        return [tool.name for tool in listed.tools]


async def _call_tool(name: str, arguments: dict[str, Any]) -> Any:
    async with _session() as session:
        result = await session.call_tool(name, arguments)
        if getattr(result, "is_error", False):
            raise RuntimeError(_error_text(result))
        structured = getattr(result, "structured_content", None)
        if structured is not None:
            return structured
        return json.loads(_error_text(result))


def _error_text(result: Any) -> str:
    blocks = getattr(result, "content", None) or []
    parts: list[str] = []
    for block in blocks:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts) if parts else "tool call failed"


@asynccontextmanager
async def _session():
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_PATH)],
    )
    async with stdio_client(parameters) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            yield session
