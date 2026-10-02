"""The IT server registers its five tools. Does not call mcp.run()."""

import sys
import unittest
from pathlib import Path

import anyio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from server import mcp

TOOL_NAMES = {
    "get_employee_info",
    "get_policy_limits",
    "check_request_eligibility",
    "evaluate_request",
    "flag_for_human_review",
}


class ServerRegistrationTests(unittest.TestCase):
    """Importing the server registers the request tools."""

    def test_five_tools_are_registered(self) -> None:
        """list_tools returns the five Internal IT tools and no others."""
        listed = anyio.run(mcp.list_tools)
        self.assertEqual({tool.name for tool in listed}, TOOL_NAMES)
