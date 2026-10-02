"""Build step: the agent makes ONE hardcoded tool call through the MCP client.

This is the suggested-approach step 5 artifact: prove the agent process can
reach the server and get a real tool result before the ReAct loop decides
anything on its own.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcp_client import call_tool

result = call_tool("get_employee_info", {"employee_id": "E001"})
print(f"get_employee_info(E001) -> {json.dumps(result, sort_keys=True)}")
