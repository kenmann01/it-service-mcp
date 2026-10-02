"""MCP client error parsing, plus one real stdio round-trip. No Ollama."""

import sys
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import anyio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcp_client import MCPClient, _call_tool, _error_text, call_tool, list_tools

TOOL_NAMES = {
    "get_employee_info",
    "get_policy_limits",
    "check_request_eligibility",
    "evaluate_request",
    "flag_for_human_review",
}


class _Block:
    """One text block on a fake tool result."""

    def __init__(self, text: str | None) -> None:
        """Store the text _error_text will read."""
        self.text = text


class _Result:
    """Stand-in for an MCP CallToolResult."""

    def __init__(
        self,
        content: list[Any] | None = None,
        is_error: bool = False,
        structured: Any = None,
    ) -> None:
        """Store the fields the client reads with getattr."""
        self.content = content
        self.is_error = is_error
        self.structured_content = structured


class _Session:
    """Session that returns one prepared tool result."""

    def __init__(self, result: _Result) -> None:
        """Store the result call_tool will hand back."""
        self._result = result

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> _Result:
        """Return the prepared result regardless of the call."""
        return self._result


def _session_for(result: _Result):
    """Build an async context manager that yields a session for this result."""

    @asynccontextmanager
    async def _session(server_path: Path | None = None):
        """Yield the fake session and then close."""
        yield _Session(result)

    return _session


class ErrorTextTests(unittest.TestCase):
    """_error_text joins text blocks or reports that the call failed."""

    def test_joins_text_blocks(self) -> None:
        """Text blocks are joined and blocks with no text are skipped."""
        result = _Result(content=[_Block("one"), _Block(""), _Block(None), object(), _Block("two")])
        self.assertEqual(_error_text(result), "one\ntwo")

    def test_missing_content_reports_failure(self) -> None:
        """No content blocks becomes the fallback failure string."""
        self.assertEqual(_error_text(_Result(content=None)), "tool call failed")
        self.assertEqual(_error_text(object()), "tool call failed")


class CallBranchesTests(unittest.TestCase):
    """Error and non-structured results, with the stdio session faked."""

    def test_error_result_raises(self) -> None:
        """is_error raises RuntimeError carrying the result text."""
        result = _Result(content=[_Block("nope")], is_error=True)
        with patch("mcp_client._session", _session_for(result)):
            with self.assertRaises(RuntimeError) as raised:
                anyio.run(_call_tool, "get_employee_info", {"employee_id": "E001"})
        self.assertEqual(str(raised.exception), "nope")

        client = MCPClient()
        client._session = _Session(result)
        with self.assertRaises(RuntimeError) as raised_on_client:
            anyio.run(client.call_tool, "get_employee_info", {"employee_id": "E001"})
        self.assertEqual(str(raised_on_client.exception), "nope")

    def test_text_json_is_parsed_when_unstructured(self) -> None:
        """JSON text is parsed when the result has no structured content."""
        result = _Result(content=[_Block('{"found": true}')])
        with patch("mcp_client._session", _session_for(result)):
            parsed = anyio.run(_call_tool, "get_employee_info", {})
        self.assertEqual(parsed, {"found": True})

        client = MCPClient()
        client._session = _Session(result)
        self.assertEqual(anyio.run(client.call_tool, "get_employee_info", {}), {"found": True})

    def test_empty_text_returns_none_on_the_client(self) -> None:
        """MCPClient.call_tool returns None when the result text is empty."""
        client = MCPClient()
        client._session = _Session(_Result(content=[]))
        with patch("mcp_client._error_text", return_value=""):
            self.assertIsNone(anyio.run(client.call_tool, "get_employee_info", {}))


class StdioTests(unittest.TestCase):
    """One real server process over stdio."""

    def test_list_and_call_employee(self) -> None:
        """list_tools names the five tools, and get_employee_info returns Grace Hopper."""
        names = list_tools()
        self.assertTrue(TOOL_NAMES <= set(names))
        info = call_tool("get_employee_info", {"employee_id": "E001"})
        self.assertEqual(info["name"], "Grace Hopper")
        self.assertTrue(info["found"])
        missing = call_tool("get_employee_info", {"employee_id": "NaN"})
        self.assertFalse(missing["found"])
        decision = call_tool(
            "evaluate_request",
            {
                "employee": "NaN",
                "role": "employee",
                "item_requested": "headphones",
                "reason": "broken",
            },
        )
        self.assertEqual(decision, {"decision": "escalate", "rule": "blank_field"})

    def test_persistent_session_lists_schemas_and_calls(self) -> None:
        """MCPClient keeps one session for schemas and a tool call."""

        async def run() -> tuple[list[dict[str, Any]], dict[str, Any]]:
            """Open the server, list schemas, and look up E001."""
            async with MCPClient() as client:
                schemas = await client.list_tool_schemas()
                info = await client.call_tool("get_employee_info", {"employee_id": "E001"})
            return schemas, info

        schemas, info = anyio.run(run)
        names = {schema["function"]["name"] for schema in schemas}
        self.assertTrue(TOOL_NAMES <= names)
        self.assertEqual(schemas[0]["type"], "function")
        self.assertIn("parameters", schemas[0]["function"])
        self.assertEqual(info["name"], "Grace Hopper")
