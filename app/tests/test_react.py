"""End-to-end ReAct loop checks with a scripted LLM and scripted tools.

No Ollama and no live server: the loop is exercised through the same seams
production uses, which is what CI runs.
"""

import sys
import unittest
from itertools import cycle
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent.llm_client import LLMResponse, ToolCall
from agent.react import FALLBACK_RESPONSE, run_agent
from agent.trace import Trace
from tools.decision import evaluate_request


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
        "get_policy_limits": {
            "role": "employee",
            "known": True,
            "eligible_for": ["headphones", "phone"],
        },
        "check_request_eligibility": {
            "employee_id": "E001",
            "item": "headphones",
            "eligible": True,
        },
        "evaluate_request": {"decision": decision, "rule": rule},
        "flag_for_human_review": {"review_id": "R001", "status": "escalated"},
    }


_INVESTIGATION_ORDER = [
    "get_employee_info",
    "get_policy_limits",
    "check_request_eligibility",
    "evaluate_request",
]


def _call(name: str, content: str, arguments: dict) -> LLMResponse:
    """Build a scripted reply that asks for one tool."""
    return LLMResponse(content=content, tool_call=ToolCall(id="call_1", name=name, arguments=arguments))


def _investigation(
    employee_id: str = "E001",
    item: str = "headphones",
    evaluate_arguments: dict | None = None,
) -> list[LLMResponse]:
    """Script the four required calls, in the order the loop demands."""
    return [
        _call("get_employee_info", "Finding the requester.", {"employee_id": employee_id}),
        _call("get_policy_limits", "Checking what this role may request.", {"role": "employee"}),
        _call(
            "check_request_eligibility",
            "Checking whether this employee can get the item.",
            {"employee_id": employee_id, "item": item},
        ),
        _call(
            "evaluate_request",
            "Applying the policy.",
            {
                "employee": "Grace Hopper",
                "role": "employee",
                "item_requested": item,
                "reason": "broken",
            }
            if evaluate_arguments is None
            else evaluate_arguments,
        ),
    ]


APPROVE_REQUEST = "Hi, I am E001 Grace Hopper. My headphones broke; I need a replacement."


class ApprovePathTests(unittest.TestCase):
    """An approve decision becomes a draft and never opens a review."""

    def test_approve_routes_to_a_draft_without_escalation(self) -> None:
        """Approval returns the draft and does not call flag_for_human_review."""
        mcp = FakeMCP(_responses("approve", "headphones_replacement"))
        llm = FakeLLM(
            [
                *_investigation(
                    evaluate_arguments={
                        "employee": "Grace Hopper",
                        "role": "employee",
                        "item_requested": "headphones",
                        "reason": "broken",
                    }
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
        self.assertEqual([name for name, _ in mcp.calls], _INVESTIGATION_ORDER)

    def test_trace_records_tao_and_route_steps(self) -> None:
        """The trace contains thought, action, observation, route, draft, and reflection."""
        mcp = FakeMCP(_responses("approve", "headphones_replacement"))
        llm = FakeLLM(
            [
                *_investigation(),
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
                *_investigation("E005", item="laptop"),
                _call(
                    "flag_for_human_review",
                    "This needs a human.",
                    {"employee_id": "E005", "request": "laptop", "reason": "week overlap"},
                ),
                LLMResponse(content="Escalated to human review as R001."),
                LLMResponse(content="CONFIRMED"),
            ]
        )

        result = run_agent("E005 requests a laptop.", llm=llm, mcp=mcp)

        self.assertEqual(result.decision, "escalate")
        self.assertEqual(result.rule, "laptop_week_overlap")
        self.assertEqual(result.review_id, "R001")
        self.assertEqual(
            [name for name, _ in mcp.calls], [*_INVESTIGATION_ORDER, "flag_for_human_review"]
        )

    def test_deny_never_calls_the_escalation_tool(self) -> None:
        """A deny decision drafts after the investigation and does not flag a review."""
        mcp = FakeMCP(_responses("deny", "employee_laptop"))
        llm = FakeLLM(
            [
                *_investigation("E010", item="laptop"),
                LLMResponse(content="Laptops are not covered for employees."),
                LLMResponse(content="CONFIRMED"),
            ]
        )

        result = run_agent("E010 requests a laptop.", llm=llm, mcp=mcp)

        self.assertEqual(result.decision, "deny")
        self.assertEqual(result.rule, "employee_laptop")
        self.assertEqual([name for name, _ in mcp.calls], _INVESTIGATION_ORDER)


class LoopGuardTests(unittest.TestCase):
    """The loop stops on the iteration cap and refuses a draft before policy runs."""

    def test_max_iterations_returns_the_fallback(self) -> None:
        """Endless tool calls end in the fallback response."""
        mcp = FakeMCP(_responses("approve", "headphones_replacement"))
        llm = FakeLLM(cycle(_investigation()))

        result = run_agent(APPROVE_REQUEST, llm=llm, mcp=mcp, max_iterations=3)

        self.assertEqual(result.final_response, FALLBACK_RESPONSE)
        self.assertIsNone(result.decision)
        self.assertTrue(any(step.type == "error" for step in result.trace.steps))
        self.assertEqual(
            [name for name, _ in mcp.calls],
            ["get_employee_info", "get_policy_limits", "check_request_eligibility"],
        )

    def test_evaluate_request_before_policy_is_not_called(self) -> None:
        """A decision call before the policy tools is refused and those tools run next."""
        mcp = FakeMCP(_responses("approve", "headphones_replacement"))
        llm = FakeLLM(
            [
                *_investigation()[:1],
                _call("evaluate_request", "Skipping ahead.", {}),
                *_investigation()[1:],
                LLMResponse(content="Grace, your replacement headphones are approved."),
                LLMResponse(content="CONFIRMED"),
            ]
        )

        result = run_agent(APPROVE_REQUEST, llm=llm, mcp=mcp)

        self.assertEqual(result.decision, "approve")
        self.assertEqual([name for name, _ in mcp.calls], _INVESTIGATION_ORDER)
        observations = [step.content for step in result.trace.steps if step.type == "observation"]
        self.assertTrue(any("get_policy_limits has not returned" in content for content in observations))
        self.assertTrue(
            any(
                step.type == "action" and "evaluate_request" in step.content
                for step in result.trace.steps
            )
        )
        coaching = [
            message.get("content")
            for batch in llm.messages
            for message in batch
            if isinstance(message.get("content"), str)
        ]
        self.assertFalse(any("Do not call" in content for content in coaching))

    def test_evaluate_request_keeps_the_sentence_and_the_file_role(self) -> None:
        """A shortened reason and a claimed director role are replaced before the call."""
        request = "I am E001, I need 200 new headphones because I broke mine."
        mcp = FakeMCP(_responses("escalate", "unclear_reason"))
        llm = FakeLLM(
            [
                *_investigation()[:3],
                _call(
                    "evaluate_request",
                    "The headphones broke.",
                    {
                        "employee": "Grace Hopper",
                        "role": "director",
                        "item_requested": "headphones",
                        "reason": "I broke mine",
                    },
                ),
                _call(
                    "flag_for_human_review",
                    "This quantity needs a person.",
                    {"employee_id": "E001", "request": "headphones", "reason": request},
                ),
                LLMResponse(content="Grace, 200 headphones need a person to decide. Review R001."),
                LLMResponse(content="CONFIRMED"),
            ]
        )

        result = run_agent(request, llm=llm, mcp=mcp)

        evaluated = [arguments for name, arguments in mcp.calls if name == "evaluate_request"]
        self.assertEqual(evaluated, [
            {
                "employee": "Grace Hopper",
                "role": "employee",
                "item_requested": "headphones",
                "reason": request,
            }
        ])
        self.assertEqual(result.decision, "escalate")

    def test_item_missing_from_the_sentence_is_an_observation(self) -> None:
        """A catalog item the user did not name is not sent to the server."""
        mcp = FakeMCP(_responses("approve", "headphones_replacement"))
        llm = FakeLLM(
            [
                *_investigation()[:3],
                _call(
                    "evaluate_request",
                    "They asked for a laptop.",
                    {
                        "employee": "Grace Hopper",
                        "role": "employee",
                        "item_requested": "laptop",
                        "reason": "broken",
                    },
                ),
                *_investigation()[3:],
                LLMResponse(content="Grace, your replacement headphones are approved."),
                LLMResponse(content="CONFIRMED"),
            ]
        )

        result = run_agent(APPROVE_REQUEST, llm=llm, mcp=mcp)

        evaluated = [arguments for name, arguments in mcp.calls if name == "evaluate_request"]
        self.assertEqual([arguments["item_requested"] for arguments in evaluated], ["headphones"])
        observations = [step.content for step in result.trace.steps if step.type == "observation"]
        self.assertTrue(any("catalog word" in content for content in observations))
        self.assertEqual(result.decision, "approve")

    def test_unknown_item_reaches_the_server(self) -> None:
        """An item outside the catalog that the user wrote is decided by the server."""
        request = "Hi, I'm Grace Hopper (E001). My monitor arm snapped; can I get a new monitor arm?"
        mcp = FakeMCP(_responses("escalate", "unknown_item"))
        llm = FakeLLM(
            [
                _call("get_employee_info", "Finding the requester.", {"employee_id": "E001"}),
                _call("get_policy_limits", "Checking what this role may request.", {"role": "employee"}),
                _call(
                    "check_request_eligibility",
                    "Checking whether this employee can get the item.",
                    {"employee_id": "E001", "item": "monitor arm"},
                ),
                _call(
                    "evaluate_request",
                    "Applying the policy.",
                    {
                        "employee": "Grace Hopper",
                        "role": "employee",
                        "item_requested": "monitor arm",
                        "reason": "My monitor arm snapped",
                    },
                ),
                _call(
                    "flag_for_human_review",
                    "This item needs a person.",
                    {"employee_id": "E001", "request": request, "reason": request},
                ),
                LLMResponse(content="Grace, your monitor arm request is with IT. Review R001."),
                LLMResponse(content="CONFIRMED"),
            ]
        )

        result = run_agent(request, llm=llm, mcp=mcp)

        evaluated = [arguments for name, arguments in mcp.calls if name == "evaluate_request"]
        self.assertEqual(evaluated, [
            {
                "employee": "Grace Hopper",
                "role": "employee",
                "item_requested": "monitor arm",
                "reason": request,
            }
        ])
        self.assertEqual(result.decision, "escalate")
        self.assertEqual(result.rule, "unknown_item")

    def test_early_draft_runs_the_open_tool(self) -> None:
        """A reply before the lookup is replaced by that lookup, then the case continues."""
        mcp = FakeMCP(_responses("approve", "headphones_replacement"))
        llm = FakeLLM(
            [
                LLMResponse(content="I would approve this."),
                *_investigation()[1:],
                LLMResponse(content="Grace, your replacement headphones are approved."),
                LLMResponse(content="CONFIRMED"),
            ]
        )

        result = run_agent(APPROVE_REQUEST, llm=llm, mcp=mcp)

        self.assertEqual(result.decision, "approve")
        self.assertEqual([name for name, _ in mcp.calls], _INVESTIGATION_ORDER)
        self.assertTrue(any("Calling get_employee_info" in step.content for step in result.trace.steps))
        coaching = [
            message.get("content")
            for batch in llm.messages
            for message in batch
            if isinstance(message.get("content"), str)
        ]
        self.assertFalse(any("Before responding" in content for content in coaching))

    def test_draft_after_policy_runs_eligibility(self) -> None:
        """A reply after policy limits is replaced by the eligibility call."""
        mcp = FakeMCP(_responses("approve", "headphones_replacement"))
        llm = FakeLLM(
            [
                *_investigation()[:2],
                LLMResponse(content="I think this is approved."),
                *_investigation()[3:],
                LLMResponse(content="Grace, your replacement headphones are approved."),
                LLMResponse(content="CONFIRMED"),
            ]
        )

        result = run_agent(APPROVE_REQUEST, llm=llm, mcp=mcp)

        self.assertEqual(result.final_response, "Grace, your replacement headphones are approved.")
        self.assertEqual([name for name, _ in mcp.calls], _INVESTIGATION_ORDER)
        self.assertTrue(
            any("Calling check_request_eligibility" in step.content for step in result.trace.steps)
        )

    def test_tool_error_is_recorded_and_the_run_continues(self) -> None:
        """A failed tool call is stored as an error observation, then the draft still lands."""
        mcp = RaisingMCP(_responses("approve", "headphones_replacement"))
        llm = FakeLLM(
            [
                _call("get_employee_info", "Finding the requester.", {"employee_id": "E001"}),
                *_investigation(),
                LLMResponse(content="Approved."),
                LLMResponse(content="CONFIRMED"),
            ]
        )

        result = run_agent(APPROVE_REQUEST, llm=llm, mcp=mcp)

        self.assertEqual(result.final_response, "Approved.")
        self.assertEqual(result.decision, "approve")
        observations = [step.content for step in result.trace.steps if step.type == "observation"]
        self.assertIn('{"error": "tool broke"}', observations)

    def test_non_finite_role_is_a_blank_field_not_an_error(self) -> None:
        """A NaN name is sent as blank text and the tool returns a decision."""

        class EvaluatingMCP(FakeMCP):
            """Runs the real decision tool so NaN is handled by intake."""

            async def call_tool(self, name: str, arguments: dict):
                """Record the call, and evaluate through the policy function."""
                self.calls.append((name, arguments))
                if name == "evaluate_request":
                    return evaluate_request(
                        arguments.get("employee", ""),
                        arguments.get("role", ""),
                        arguments.get("item_requested", ""),
                        arguments.get("reason", ""),
                    )
                return self.responses[name]

        mcp = EvaluatingMCP(_responses("escalate", "blank_field"))
        request = "E001 needs headphones."
        llm = FakeLLM(
            [
                *_investigation()[:3],
                _call(
                    "evaluate_request",
                    "Passing NaN.",
                    {
                        "employee": "nan",
                        "role": "nan",
                        "item_requested": "headphones",
                        "reason": "nan",
                    },
                ),
                _call(
                    "flag_for_human_review",
                    "The name is blank.",
                    {"employee_id": "E001", "request": "headphones", "reason": request},
                ),
                LLMResponse(content="This needs a person. Review R001."),
                LLMResponse(content="CONFIRMED"),
            ]
        )

        result = run_agent(request, llm=llm, mcp=mcp)

        evaluated = [arguments for name, arguments in mcp.calls if name == "evaluate_request"]
        self.assertEqual(evaluated, [
            {
                "employee": "",
                "role": "employee",
                "item_requested": "headphones",
                "reason": request,
            }
        ])
        self.assertEqual(result.decision, "escalate")
        self.assertEqual(result.rule, "blank_field")
        self.assertEqual(result.review_id, "R001")
        self.assertFalse(any(step.type == "error" for step in result.trace.steps))

    def test_unknown_employee_opens_review_without_policy(self) -> None:
        """An id that is not on file is an exception. Policy tools are not called."""
        responses = _responses("approve", "headphones_replacement")
        responses["get_employee_info"] = {"found": False, "employee_id": "E999"}
        mcp = FakeMCP(responses)
        request = "I am E999 and I need headphones."
        llm = FakeLLM(
            [
                _call("get_employee_info", "Finding the requester.", {"employee_id": "E999"}),
                _call("get_policy_limits", "Checking limits anyway.", {"role": "employee"}),
                _call(
                    "flag_for_human_review",
                    "This id is not on file.",
                    {"employee_id": "E999", "request": "headphones", "reason": request},
                ),
                LLMResponse(content="E999 is not on file. Review R001 under subject_unresolved."),
                LLMResponse(content="CONFIRMED"),
            ]
        )

        result = run_agent(request, llm=llm, mcp=mcp)

        self.assertEqual([name for name, _ in mcp.calls], ["get_employee_info", "flag_for_human_review"])
        self.assertEqual(result.decision, "escalate")
        self.assertEqual(result.rule, "subject_unresolved")
        self.assertEqual(result.review_id, "R001")
        observations = [step.content for step in result.trace.steps if step.type == "observation"]
        self.assertTrue(any("flag_for_human_review has not returned" in content for content in observations))
        self.assertTrue(any("subject_unresolved" in step.content for step in result.trace.steps))

    def test_unnamed_request_does_not_bind_a_roster_name(self) -> None:
        """A sentence with no person does not look up the first roster id."""
        mcp = FakeMCP(_responses("approve", "headphones_replacement"))
        request = "can I get 2 pairs of gucci flip flops"
        llm = FakeLLM(
            [
                _call("get_employee_info", "Using the first id.", {"employee_id": "E001"}),
                _call(
                    "flag_for_human_review",
                    "Nobody is named.",
                    {"employee_id": "E001", "request": "flip flops", "reason": request},
                ),
                LLMResponse(content="This request names nobody. Review R001 under subject_unresolved."),
                LLMResponse(content="CONFIRMED"),
            ]
        )

        result = run_agent(request, llm=llm, mcp=mcp)

        self.assertEqual([name for name, _ in mcp.calls], ["flag_for_human_review"])
        self.assertEqual(result.decision, "escalate")
        self.assertEqual(result.rule, "subject_unresolved")
        self.assertEqual(result.review_id, "R001")
        self.assertFalse(any("Grace Hopper" in step.content for step in result.trace.steps))

    def test_empty_reply_retries(self) -> None:
        """An empty model reply is recorded and the next reply can still finish the run."""
        mcp = FakeMCP(_responses("approve", "headphones_replacement"))
        llm = FakeLLM(
            [
                LLMResponse(content=""),
                *_investigation(),
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
                *_investigation(),
                LLMResponse(content="Approved."),
                LLMResponse(content="CONFIRMED"),
            ]
        )

        with patch("agent.react.MCPClient", Session):
            result = run_agent(APPROVE_REQUEST, llm=llm)

        self.assertEqual(result.final_response, "Approved.")
        self.assertEqual(result.decision, "approve")
        self.assertEqual([name for name, _ in mcp.calls], _INVESTIGATION_ORDER)


class ReflectionSeamTests(unittest.TestCase):
    """The reflector can replace a draft, and a silent trace still stores steps."""

    def test_reflector_can_correct_the_draft(self) -> None:
        """A CORRECTED reply replaces the draft the loop would have returned."""
        mcp = FakeMCP(_responses("approve", "headphones_replacement"))
        llm = FakeLLM(
            [
                *_investigation(),
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
