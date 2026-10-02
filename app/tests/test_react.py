"""End-to-end ReAct loop checks with a scripted LLM and scripted tools.

No Ollama and no live server: the loop is exercised through the same seams
production uses, which is what CI runs.
"""

import sys
import unittest
from itertools import repeat
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent.llm_client import LLMResponse, ToolCall
from agent.react import FALLBACK_RESPONSE, run_agent
from agent.trace import Trace


class FakeLLM:
    """Scripted chat(): returns prepared LLMResponse objects in order."""

    def __init__(self, script) -> None:
        """Store the replies this fake will return, in order."""
        self.script = iter(script)
        self.messages: list[list[dict]] = []

    def chat(self, messages, tools=None) -> LLMResponse:
        """Record the messages and return the next scripted reply."""
        self.messages.append(messages)
        return next(self.script)


class FakeMCP:
    """Scripted tools: returns one prepared result per tool name, records calls."""

    def __init__(self, responses: dict) -> None:
        """Store one prepared result per tool name."""
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    async def list_tool_schemas(self) -> list[dict]:
        """Advertise one function schema per prepared tool."""
        return [{"type": "function", "function": {"name": name, "parameters": {}}} for name in self.responses]

    async def call_tool(self, name: str, arguments: dict):
        """Record the call and return the prepared result for that tool."""
        self.calls.append((name, arguments))
        return self.responses[name]


class RaisingMCP(FakeMCP):
    """Raises on the first call_tool, then behaves like FakeMCP."""

    def __init__(self, responses: dict) -> None:
        """Remember the responses and that the first call has not failed yet."""
        super().__init__(responses)
        self._raised = False

    async def call_tool(self, name: str, arguments: dict):
        """Fail the first call with RuntimeError, then return the scripted result."""
        if not self._raised:
            self._raised = True
            self.calls.append((name, arguments))
            raise RuntimeError("tool broke")
        return await super().call_tool(name, arguments)


def _responses(decision: str, rule: str) -> dict:
    """Build the tool results used by a scripted approve, deny, or escalate path."""
    return {
        "get_employee_info": {
            "found": True,
            "employee_id": "E001",
            "name": "Grace Hopper",
            "role": "employee",
            "tenure_years": 14,
            "equipment": ["headphones", "laptop"],
        },
        "evaluate_request": {"decision": decision, "rule": rule},
        "flag_for_human_review": {"review_id": "R001", "status": "escalated"},
    }


def _call(name: str, content: str, arguments: dict) -> LLMResponse:
    """Build a scripted reply that asks for one tool."""
    return LLMResponse(content=content, tool_call=ToolCall(id="call_1", name=name, arguments=arguments))


APPROVE_REQUEST = "Hi, I am E001 Grace Hopper. My headphones broke; I need a replacement."


class ApprovePathTests(unittest.TestCase):
    """An approve decision becomes a draft and never opens a review."""

    def test_approve_routes_to_a_draft_without_escalation(self) -> None:
        """Approval returns the draft and does not call flag_for_human_review."""
        mcp = FakeMCP(_responses("approve", "headphones_replacement"))
        llm = FakeLLM(
            [
                _call("get_employee_info", "Finding the requester.", {"employee_id": "E001"}),
                _call(
                    "evaluate_request",
                    "Applying the policy.",
                    {
                        "employee": "Grace Hopper",
                        "role": "employee",
                        "item_requested": "headphones",
                        "reason": "broken",
                    },
                ),
                LLMResponse(content="Grace, your replacement headphones are approved."),
                LLMResponse(content="CONFIRMED"),
            ]
        )

        result = run_agent(APPROVE_REQUEST, llm=llm, mcp=mcp)

        self.assertEqual(result.final_response, "Grace, your replacement headphones are approved.")
        self.assertEqual(result.decision, "approve")
        self.assertEqual(result.rule, "headphones_replacement")
        self.assertIsNone(result.review_id)
        self.assertEqual(
            [name for name, _ in mcp.calls], ["get_employee_info", "evaluate_request"]
        )

    def test_trace_records_tao_and_route_steps(self) -> None:
        """The trace contains thought, action, observation, route, draft, and reflection."""
        mcp = FakeMCP(_responses("approve", "headphones_replacement"))
        llm = FakeLLM(
            [
                _call("get_employee_info", "Finding the requester.", {"employee_id": "E001"}),
                _call("evaluate_request", "Applying the policy.", {}),
                LLMResponse(content="Approved."),
                LLMResponse(content="CONFIRMED"),
            ]
        )

        result = run_agent(APPROVE_REQUEST, llm=llm, mcp=mcp)

        types = [step.type for step in result.trace.steps]
        for expected in ("thought", "action", "observation", "route", "draft", "reflection"):
            self.assertIn(expected, types)
        route = next(step for step in result.trace.steps if step.type == "route")
        self.assertIn("approve", route.content)


class EscalatePathTests(unittest.TestCase):
    """Escalate opens a review; deny does not."""

    def test_escalation_flags_for_human_review(self) -> None:
        """An escalate decision calls flag_for_human_review and keeps the review id."""
        mcp = FakeMCP(_responses("escalate", "laptop_week_overlap"))
        llm = FakeLLM(
            [
                _call("get_employee_info", "Finding the requester.", {"employee_id": "E005"}),
                _call("evaluate_request", "Applying the policy.", {}),
                _call(
                    "flag_for_human_review",
                    "This needs a human.",
                    {"employee_id": "E005", "request": "laptop", "reason": "week overlap"},
                ),
                LLMResponse(content="Escalated to human review as R001."),
                LLMResponse(content="CONFIRMED"),
            ]
        )

        result = run_agent("Manager laptop request.", llm=llm, mcp=mcp)

        self.assertEqual(result.decision, "escalate")
        self.assertEqual(result.rule, "laptop_week_overlap")
        self.assertEqual(result.review_id, "R001")
        self.assertEqual(
            [name for name, _ in mcp.calls][-1], "flag_for_human_review"
        )

    def test_deny_never_calls_the_escalation_tool(self) -> None:
        """A deny decision stops after evaluate_request."""
        mcp = FakeMCP(_responses("deny", "employee_laptop"))
        llm = FakeLLM(
            [
                _call("get_employee_info", "Finding the requester.", {"employee_id": "E010"}),
                _call("evaluate_request", "Applying the policy.", {}),
                LLMResponse(content="Laptops are not covered for employees."),
                LLMResponse(content="CONFIRMED"),
            ]
        )

        result = run_agent("Employee laptop request.", llm=llm, mcp=mcp)

        self.assertEqual(result.decision, "deny")
        self.assertEqual(result.rule, "employee_laptop")
        self.assertNotIn("flag_for_human_review", [name for name, _ in mcp.calls])


class LoopGuardTests(unittest.TestCase):
    """The loop stops on the iteration cap and refuses a draft before policy runs."""

    def test_max_iterations_returns_the_fallback(self) -> None:
        """Endless tool calls end in the fallback response."""
        mcp = FakeMCP(_responses("approve", "headphones_replacement"))
        llm = FakeLLM(
            repeat(
                _call("evaluate_request", "Applying the policy.", {}),
            )
        )

        result = run_agent(APPROVE_REQUEST, llm=llm, mcp=mcp, max_iterations=3)

        self.assertEqual(result.final_response, FALLBACK_RESPONSE)
        self.assertEqual(result.decision, "approve")
        self.assertTrue(any(step.type == "error" for step in result.trace.steps))

    def test_draft_without_policy_check_is_bounced(self) -> None:
        """A draft before evaluate_request is rejected and the tool is called next."""
        mcp = FakeMCP(_responses("approve", "headphones_replacement"))
        llm = FakeLLM(
            [
                LLMResponse(content="I would approve this."),
                _call("evaluate_request", "Checking the policy first.", {}),
                LLMResponse(content="Grace, your replacement headphones are approved."),
                LLMResponse(content="CONFIRMED"),
            ]
        )

        result = run_agent(APPROVE_REQUEST, llm=llm, mcp=mcp)

        self.assertEqual(result.decision, "approve")
        self.assertTrue(
            any("bouncing" in step.content for step in result.trace.steps)
        )
        self.assertEqual(
            [name for name, _ in mcp.calls][0], "evaluate_request"
        )

    def test_tool_error_is_recorded_and_the_run_continues(self) -> None:
        """A failed tool call is stored as an error observation, then the draft still lands."""
        mcp = RaisingMCP(_responses("approve", "headphones_replacement"))
        llm = FakeLLM(
            [
                _call("get_employee_info", "Finding the requester.", {"employee_id": "E001"}),
                _call("evaluate_request", "Applying the policy.", {}),
                LLMResponse(content="Approved."),
                LLMResponse(content="CONFIRMED"),
            ]
        )

        result = run_agent(APPROVE_REQUEST, llm=llm, mcp=mcp)

        self.assertEqual(result.final_response, "Approved.")
        self.assertEqual(result.decision, "approve")
        observations = [step.content for step in result.trace.steps if step.type == "observation"]
        self.assertIn('{"error": "tool broke"}', observations)

    def test_empty_reply_retries(self) -> None:
        """An empty model reply is recorded and the next reply can still finish the run."""
        mcp = FakeMCP(_responses("approve", "headphones_replacement"))
        llm = FakeLLM(
            [
                LLMResponse(content=""),
                _call("evaluate_request", "Applying the policy.", {}),
                LLMResponse(content="Approved after retry."),
                LLMResponse(content="CONFIRMED"),
            ]
        )

        result = run_agent(APPROVE_REQUEST, llm=llm, mcp=mcp)

        self.assertEqual(result.final_response, "Approved after retry.")
        self.assertTrue(any("empty model reply" in step.content for step in result.trace.steps))


class LiveSessionTests(unittest.TestCase):
    """run_agent opens an MCP client when the caller does not pass one."""

    def test_run_without_mcp_uses_the_client_session(self) -> None:
        """A patched MCPClient yields the fake server and the approve path still finishes."""
        mcp = FakeMCP(_responses("approve", "headphones_replacement"))

        class Session:
            """Async context manager that yields the prepared fake server."""

            def __init__(self, server_path: object = None) -> None:
                """Accept the server path the real client would store."""
                self.server_path = server_path

            async def __aenter__(self) -> FakeMCP:
                """Hand the fake server to the TAO loop."""
                return mcp

            async def __aexit__(self, *exc_info: object) -> None:
                """Close without touching a real process."""
                return None

        llm = FakeLLM(
            [
                _call("get_employee_info", "Finding the requester.", {"employee_id": "E001"}),
                _call("evaluate_request", "Applying the policy.", {}),
                LLMResponse(content="Approved."),
                LLMResponse(content="CONFIRMED"),
            ]
        )

        with patch("agent.react.MCPClient", Session):
            result = run_agent(APPROVE_REQUEST, llm=llm)

        self.assertEqual(result.final_response, "Approved.")
        self.assertEqual(result.decision, "approve")
        self.assertEqual(
            [name for name, _ in mcp.calls], ["get_employee_info", "evaluate_request"]
        )


class ReflectionSeamTests(unittest.TestCase):
    """The reflector can replace a draft, and a silent trace still stores steps."""

    def test_reflector_can_correct_the_draft(self) -> None:
        """A CORRECTED reply replaces the draft the loop would have returned."""
        mcp = FakeMCP(_responses("approve", "headphones_replacement"))
        llm = FakeLLM(
            [
                _call("get_employee_info", "Finding the requester.", {"employee_id": "E001"}),
                _call("evaluate_request", "Applying the policy.", {}),
                LLMResponse(content="Draft v1."),
                LLMResponse(content="CORRECTED: Grace, your replacement headphones are approved under rule headphones_replacement."),
            ]
        )

        result = run_agent(APPROVE_REQUEST, llm=llm, mcp=mcp)

        self.assertTrue(
            result.final_response.startswith("Grace, your replacement headphones")
        )
        self.assertTrue(
            any("corrected" in step.content.lower() for step in result.trace.steps)
        )

    def test_trace_can_run_silently(self) -> None:
        """A trace with echo off still renders the step it stored."""
        trace = Trace(echo=False)
        trace.add("thought", "hidden")
        self.assertEqual(trace.to_text(), "[THOUGHT] hidden")


if __name__ == "__main__":
    unittest.main()
