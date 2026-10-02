"""Minimal MCP client: connects to minimal_server.py, lists tools, calls one.

This is the suggested-approach step 3 artifact: proof that the plumbing works
end to end before the real tools are built.
"""

import sys
from pathlib import Path

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

SERVER = Path(__file__).resolve().parent / "minimal_server.py"


async def main() -> None:
    """Connect to the minimal server, list its tools, and call ping."""
    parameters = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    print(f"Connecting to {SERVER.name} over stdio...")
    async with stdio_client(parameters) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = [tool.name for tool in listed.tools]
            print(f"Registered tools: {names}")
            print("Calling ping()...")
            result = await session.call_tool("ping", {})
            print(f"ping() -> {result.content[0].text}")


if __name__ == "__main__":
    anyio.run(main)
