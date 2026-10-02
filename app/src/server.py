from mcp.server import MCPServer
from mcp_types import ToolAnnotations

from tools.eligibility import check_request_eligibility
from tools.employee_info import get_employee_info
from tools.human_review import flag_for_human_review
from tools.policy_limits import get_policy_limits

mcp = MCPServer("Internal IT Service")

_READ_ONLY = ToolAnnotations(read_only_hint=True)
_ESCALATE = ToolAnnotations(read_only_hint=False, destructive_hint=False)

mcp.tool(annotations=_READ_ONLY)(get_employee_info)
mcp.tool(annotations=_READ_ONLY)(get_policy_limits)
mcp.tool(annotations=_READ_ONLY)(check_request_eligibility)
mcp.tool(annotations=_ESCALATE)(flag_for_human_review)


if __name__ == "__main__":
    mcp.run()
