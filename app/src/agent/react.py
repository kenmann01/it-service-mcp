"""Planner -> TAO -> Reflector, the whiteboard pipeline.

Planner: the system prompt below; the model states its plan before acting.
TAO: the Thought/Action/Observation loop over the MCP server's tools.
Routing: an explicit [ROUTE] step after evaluate_request returns a decision.
Reflector: agent.reflection.reflect confirms or corrects the final draft.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import anyio

from agent.llm_client import OllamaClient
from agent.reflection import reflect
from agent.trace import Trace
from mcp_client import MCPClient
from tools.data_store import load_employees

MAX_ITERATIONS = 8

_ROUTES = {
    "approve": "draft the approval, naming the rule",
    "deny": "draft the refusal, naming the rule; do not call flag_for_human_review",
    "escalate": "call flag_for_human_review, then draft the handoff with the review id",
}


def _roster() -> str:
    lines = []
    for info in load_employees():
        lines.append(f"- {info['employee_id']}: {info['name']} ({info['role']})")
    return "\n".join(lines)


def _build_system_prompt() -> str:
    return f"""You are the IT equipment request agent for the Internal IT Service MCP server.

REQUEST
The user submits an equipment request in natural language. Extract four fields:
employee (the person's name), role, item_requested (headphones, phone, or laptop),
and reason.

ROSTER
{_roster()}
When the request names a person without an id, find their id above. When it gives
an id, use it as given.

TOOLS
- get_employee_info(employee_id): the employee's role, tenure, and equipment on file. Call this first to establish who is asking and what their role is.
- get_policy_limits(role): what a role is eligible for and how often.
- check_request_eligibility(employee_id, item): static coverage check for a role and item.
- evaluate_request(employee, role, item_requested, reason): applies the full written policy and returns two fields, decision (approve, deny, or escalate) and rule (the rule id). This tool decides the request; never decide policy yourself.
- flag_for_human_review(employee_id, request, reason): side-effecting escalation to the human review queue.

PLAN
1. Call get_employee_info to identify the requester and their role.
2. Call evaluate_request with the four extracted fields. Use the role returned by get_employee_info, not one you infer. Pass the reason text as the user wrote it.
3. Route by the decision evaluate_request returned: {json.dumps(_ROUTES)}
4. Write the final draft and nothing else. Keep it under six sentences and address the requester by name.

Before every tool call, write one short sentence explaining why. Never guess: an
ambiguous or out-of-scope request must reach a decision through evaluate_request,
and only an escalate decision goes to flag_for_human_review. Do not invent policy
rules, and do not promise equipment the tools did not approve."""


SYSTEM_PROMPT = _build_system_prompt()

FALLBACK_RESPONSE = (
    "Unable to reach a decision after multiple attempts. "
    "Please try again or contact IT support."
)


@dataclass
class AgentResult:
    request: str
    final_response: str
    trace: Trace
    decision: str | None = None
    rule: str | None = None
    review_id: str | None = None


def run_agent(
    request: str,
    llm: Any = None,
    mcp: Any = None,
    max_iterations: int = MAX_ITERATIONS,
) -> AgentResult:
    """Run one request through the pipeline.

    llm and mcp are seams for tests: pass a FakeLLM and a FakeMCP to run the
    loop without Ollama or a live server. Production callers pass neither.
    """
    llm = llm or OllamaClient.from_env()
    if mcp is not None:
        return anyio.run(_react_loop, request, llm, mcp, max_iterations)
    return anyio.run(_react_loop_live, request, llm, max_iterations)


async def _react_loop_live(request: str, llm: Any, max_iterations: int) -> AgentResult:
    async with MCPClient() as server:
        return await _react_loop(request, llm, server, max_iterations)


async def _react_loop(
    request: str, llm: Any, mcp: Any, max_iterations: int
) -> AgentResult:
    trace = Trace()
    tools = await mcp.list_tool_schemas()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": request},
    ]
    decision: str | None = None
    rule: str | None = None
    review_id: str | None = None

    for iteration in range(1, max_iterations + 1):
        response = llm.chat(messages, tools=tools)

        if response.has_tool_call and response.tool_call:
            action = response.tool_call
            thought = response.content or f"I need to call {action.name}."
            trace.add("thought", f"(iteration {iteration}) {thought}")
            trace.add(
                "action", f"{action.name}({json.dumps(action.arguments, sort_keys=True)})"
            )
            try:
                observation = await mcp.call_tool(action.name, action.arguments)
            except (RuntimeError, json.JSONDecodeError) as error:
                observation = {"error": str(error)}
            trace.add("observation", json.dumps(observation, sort_keys=True, default=str))

            if action.name == "evaluate_request" and isinstance(observation, dict):
                decision = observation.get("decision")
                rule = observation.get("rule")
                if decision:
                    trace.add("route", f"{decision} ({rule}) -> {_ROUTES.get(decision, 'unknown route')}")
            if action.name == "flag_for_human_review" and isinstance(observation, dict):
                review_id = observation.get("review_id")

            messages.append(
                {"role": "assistant", "content": thought, "tool_calls": [action.to_dict()]}
            )
            messages.append(
                {
                    "role": "tool",
                    "content": json.dumps(observation, sort_keys=True, default=str),
                    "tool_call_id": action.id,
                }
            )
            continue

        draft = (response.content or "").strip()
        if not draft:
            trace.add("error", f"Iteration {iteration}: empty model reply; retrying.")
            continue

        trace.add("draft", draft)
        reflection_result = reflect(draft, trace, llm)
        trace.add("reflection", reflection_result.summary)
        return AgentResult(
            request=request,
            final_response=reflection_result.final_draft,
            trace=trace,
            decision=decision,
            rule=rule,
            review_id=review_id,
        )

    trace.add("error", f"Max iterations ({max_iterations}) reached without a final answer.")
    return AgentResult(
        request=request,
        final_response=FALLBACK_RESPONSE,
        trace=trace,
        decision=decision,
        rule=rule,
        review_id=review_id,
    )
