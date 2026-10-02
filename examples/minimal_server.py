"""The simplest possible MCP server: one trivial tool, no business logic.

This is the suggested-approach step 1 artifact: prove the SDK installs, the
server starts, and the tool registers, before any real business logic exists.
"""

from mcp.server import MCPServer
from mcp_types import ToolAnnotations

mcp = MCPServer("Minimal Example")

_READ_ONLY = ToolAnnotations(read_only_hint=True)


def ping() -> str:
    """Return pong."""
    return "pong"


mcp.tool(annotations=_READ_ONLY)(ping)


if __name__ == "__main__":
    mcp.run()
