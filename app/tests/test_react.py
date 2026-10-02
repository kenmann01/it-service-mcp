"""End-to-end ReAct loop checks with a scripted LLM and scripted tools.

No Ollama and no live server: the loop is exercised through the same seams
production uses, which is what CI runs.
"""

import sys
import unittest
from itertools import repeat
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent.llm_client import LLMResponse, ToolCall
from agent.react import FALLBACK_RESPONSE, run_agent
from agent.trace import Trace


class FakeLLM:
    """Scripted chat(): returns prepared LLMResponse objects in order."""

    def __init__(self, script) -> None:
        self.script = iter(script)
        self.messages: list[list[dict]] = []

    def chat(self, messages, tools=None) -> LLMResponse:
        self.messages.append(messages)
        return next(self.script)


class FakeMCP:
    """Scripted tools: returns one prepared result per tool name, records calls."""

    def __init__(self, responses: dict) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    async def list_tool_schemas(self) -> list[dict]:
        return [{"type": "function", "function": {"name": name, "parameters": {}}} for name in self.responses]

    async def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        return self.responses[name]


def _responses(decision: str, rule: str) -> dict:
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
    return LLMResponse(content=content, tool_call=ToolCall(id="call_1", name=name, arguments=arguments))


APPROVE_REQUEST = "Hi, I am E001 Grace Hopper. My headphones broke; I need a replacement."


class ApprovePathTests(unittest.TestCase):
    def test_approve_routes_to_a_draft_without_escalation(self) -> None:
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
    def test_escalation_flags_for_human_review(self) -> None:
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
    def test_max_iterations_returns_the_fallback(self) -> None:
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


class ReflectionSeamTests(unittest.TestCase):
    def test_reflector_can_correct_the_draft(self) -> None:
        mcp = FakeMCP(_responses("approve", "headphones_replacement"))
        llm = FakeLLM(
            [
                _call("get_employee_info", "Finding the requester.", {"employee_id": "E001"}),
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
        trace = Trace(echo=False)
        trace.add("thought", "hidden")
        self.assertEqual(trace.to_text(), "[THOUGHT] hidden")


if __name__ == "__main__":
    unittest.main()
