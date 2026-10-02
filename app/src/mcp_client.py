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
    """Open a session and return the tool names it advertises."""
    async with _session() as session:
        listed = await session.list_tools()
        return [tool.name for tool in listed.tools]


async def _call_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Open a session, call one tool, and return structured content or JSON."""
    async with _session() as session:
        result = await session.call_tool(name, arguments)
        if getattr(result, "is_error", False):
            raise RuntimeError(_error_text(result))
        structured = getattr(result, "structured_content", None)
        if structured is not None:
            return structured
        return json.loads(_error_text(result))


def _error_text(result: Any) -> str:
    """Join text blocks from an MCP tool result."""
    blocks = getattr(result, "content", None) or []
    parts: list[str] = []
    for block in blocks:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts) if parts else "tool call failed"


@asynccontextmanager
async def _session(server_path: Path | None = None):
    """Start the IT server over stdio and yield an initialized client session."""
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(server_path or SERVER_PATH)],
    )
    async with stdio_client(parameters) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            yield session


class MCPClient:
    """One persistent stdio server session for a whole agent run.

    The TAO loop calls several tools per request; keeping the session open
    avoids relaunching the server for every call. Tool schemas come back in
    OpenAI/Ollama function format, ready to pass to the LLM.
    """

    def __init__(self, server_path: Path | None = None) -> None:
        """Remember which server script this client will launch."""
        self.server_path = server_path or SERVER_PATH

    async def __aenter__(self) -> "MCPClient":
        """Start the server and keep its session for the agent run."""
        self._session_cm = _session(self.server_path)
        self._session = await self._session_cm.__aenter__()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Close the server session."""
        await self._session_cm.__aexit__(*exc_info)

    async def list_tool_schemas(self) -> list[dict[str, Any]]:
        """Return tool schemas in OpenAI/Ollama function format."""
        listed = await self._session.list_tools()
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.input_schema,
                },
            }
            for tool in listed.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Call one tool on the open session and return its JSON result."""
        result = await self._session.call_tool(name, arguments)
        if getattr(result, "is_error", False):
            raise RuntimeError(_error_text(result))
        structured = getattr(result, "structured_content", None)
        if structured is not None:
            return structured
        text = _error_text(result)
        return json.loads(text) if text else None
