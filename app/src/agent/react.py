"""Planner -> TAO -> Reflector, the whiteboard pipeline.

Planner: the system prompt below; the model states its plan before acting.
TAO: the Thought/Action/Observation loop over the MCP server's tools.
Routing: an explicit [ROUTE] step after evaluate_request returns a decision.
Reflector: agent.reflection.reflect confirms or corrects the final draft.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import anyio
from pydantic import ValidationError

from agent.llm_client import OllamaClient, ToolCall
from agent.reflection import reflect
from agent.trace import Trace
from mcp_client import MCPClient
from tools.data_store import load_employees
from tools.intake import as_text

MAX_ITERATIONS = 12

_ROUTES = {
    "approve": "draft the approval, naming the rule",
    "deny": "draft the refusal, naming the rule; do not call flag_for_human_review",
    "escalate": "call flag_for_human_review, then draft the handoff with the review id",
}

# A draft is refused until each of these has returned without an error.
_INVESTIGATION = (
    "get_employee_info",
    "get_policy_limits",
    "check_request_eligibility",
    "evaluate_request",
)


def _investigation_succeeded(name: str, observation: Any) -> bool:
    """True when this call is one of the required tools and did not error."""
    return name in _INVESTIGATION and isinstance(observation, dict) and "error" not in observation


def _subject_unresolved(employee_info: dict[str, Any] | None) -> bool:
    """True when the directory lookup returned and the id is not on file."""
    return isinstance(employee_info, dict) and employee_info.get("found") is False


def _next_step(
    investigated: set[str],
    employee_info: dict[str, Any] | None,
    decision: str | None,
    flagged: bool,
    identify: bool,
) -> str | None:
    """Return the only tool the current case state allows, or None when a draft is allowed.

    A request that names someone still starts with get_employee_info. A bound
    employee then walks the four investigation tools in order. An id that is
    not on file, or a request that names nobody, is an exception: the next tool
    is the review flag, and policy, eligibility, and evaluate_request are not
    part of that case. An escalate effect from the control register also waits
    for the review flag.
    """
    if identify and "get_employee_info" not in investigated:
        return "get_employee_info"
    if not identify and "get_employee_info" not in investigated:
        if not flagged:
            return "flag_for_human_review"
        return None
    if _subject_unresolved(employee_info):
        if not flagged:
            return "flag_for_human_review"
        return None
    for name in _INVESTIGATION:
        if name not in investigated:
            return name
    if decision == "escalate" and not flagged:
        return "flag_for_human_review"
    return None


_ID_RE = re.compile(r"\bE\d+\b", re.IGNORECASE)


def _mentioned_employee(request: str) -> str | None:
    """Return the id written in the request, or the roster id for a full name it writes.

    A request that contains neither is unresolved. The roster is not a default person.
    """
    match = _ID_RE.search(request)
    if match:
        return match.group(0).upper()
    text = request.lower()
    for info in load_employees():
        if info["name"].lower() in text:
            return info["employee_id"]
    return None


_ITEM_PATTERNS = (
    ("headphones", re.compile(r"\bheadphones?\b", re.IGNORECASE)),
    ("phone", re.compile(r"\bphones?\b", re.IGNORECASE)),
    ("laptop", re.compile(r"\blaptops?\b", re.IGNORECASE)),
)
_ITEM_ALIASES = {
    "headphone": "headphones",
    "headphones": "headphones",
    "phone": "phone",
    "phones": "phone",
    "laptop": "laptop",
    "laptops": "laptop",
}


def _roster() -> str:
    """Format the employee roster the planner uses to resolve names to ids."""
    lines = []
    for info in load_employees():
        lines.append(f"- {info['employee_id']}: {info['name']}")
    return "\n".join(lines)


def _item_in_request(request: str) -> str | None:
    """Return the catalog item named in the request, if one is named."""
    for name, pattern in _ITEM_PATTERNS:
        if pattern.search(request):
            return name
    return None


def _arguments_for_step(
    name: str,
    request: str,
    employee_info: dict[str, Any] | None,
    mentioned: str | None,
) -> dict[str, Any] | None:
    """Build the arguments for the open step from the request and the lookup.

    The loop uses this when the model writes a reply before that step has run.
    """
    employee_id = mentioned or ""
    if isinstance(employee_info, dict) and employee_info.get("employee_id"):
        employee_id = str(employee_info["employee_id"])
    if name == "get_employee_info":
        if not mentioned:
            return None
        return {"employee_id": mentioned}
    if name == "get_policy_limits":
        role = ""
        if isinstance(employee_info, dict) and isinstance(employee_info.get("role"), str):
            role = employee_info["role"].strip()
        if not role:
            return None
        return {"role": role}
    if name == "check_request_eligibility":
        item = _item_in_request(request)
        if not employee_id or not item:
            return None
        return {"employee_id": employee_id, "item": item}
    if name == "evaluate_request":
        item = _item_in_request(request)
        if item is None:
            return None
        person = ""
        if isinstance(employee_info, dict) and isinstance(employee_info.get("name"), str):
            person = employee_info["name"]
        prepared, problem = _prepare_evaluate(
            {
                "employee": person or employee_id,
                "role": "",
                "item_requested": item,
                "reason": request,
            },
            request,
            employee_info,
        )
        if problem:
            return None
        return prepared
    if name == "flag_for_human_review":
        return {
            "employee_id": employee_id or "unknown",
            "request": request,
            "reason": request,
        }
    return None


def _catalog_item(sentence: str, claimed: str) -> str | None:
    """Return the catalog word when the claim is that word and the sentence says it."""
    canonical = _ITEM_ALIASES.get(claimed.strip().lower())
    if canonical is None:
        return None
    pattern = next(compiled for name, compiled in _ITEM_PATTERNS if name == canonical)
    if pattern.search(sentence):
        return canonical
    return None


def _prepare_evaluate(
    arguments: dict[str, Any], request: str, employee: dict[str, Any] | None
) -> tuple[dict[str, Any], str | None]:
    """Fill reason and role from data the model must not paraphrase.

    reason is the raw sentence, so a count such as 2000 cannot be dropped.
    role comes from the employee lookup when that lookup found the person.
    item_requested must be a catalog word that appears in the sentence.
    """
    prepared = dict(arguments)
    prepared["reason"] = request
    if isinstance(employee, dict) and employee.get("found") and isinstance(employee.get("role"), str):
        role = employee["role"].strip()
        if role:
            prepared["role"] = role
    claimed = prepared.get("item_requested")
    claimed_text = claimed if isinstance(claimed, str) else ""
    item = _catalog_item(request, claimed_text)
    if item is None:
        return prepared, "item_requested is not a catalog word in the request"
    prepared["item_requested"] = item
    return prepared, None


def _build_system_prompt() -> str:
    """Build the planner prompt: roster, tool names, and the route table."""
    return f"""You are the IT equipment request agent for the Internal IT Service MCP server.

The user submits one equipment request. Call the tools. The server decides.

ROSTER
{_roster()}
When the request writes an id, use that id. When it writes a full name from the roster and no id, use that person's id. When it names nobody, do not choose an id from the roster.

TOOLS
- get_employee_info(employee_id)
- get_policy_limits(role)
- check_request_eligibility(employee_id, item)
- evaluate_request(employee, role, item_requested, reason)
- flag_for_human_review(employee_id, request, reason)

PLAN
1. If the request names a person, call get_employee_info for that person.
2. If the request names nobody, the decision is escalate and the rule is subject_unresolved. Call flag_for_human_review, then draft the handoff with the review id and that rule. get_employee_info is not part of that case.
3. If the lookup has found set to false, the decision is the same exception. Call flag_for_human_review. Policy limits, eligibility, and evaluate_request are not part of that case.
4. If the person was found, call get_policy_limits with the role from that observation.
5. Call check_request_eligibility with the employee id and the item.
6. Call evaluate_request. The server applies the policy.
7. Route by the decision: {json.dumps(_ROUTES)}
8. Write the draft to the requester. Cite the rule, and stay under six sentences. Use a person's name only when the request or the lookup contains it.

Before every tool call, write one short sentence explaining why. Never decide policy yourself. When an observation names a tool that has not returned, call that tool next. The draft waits until that call has returned."""


SYSTEM_PROMPT = _build_system_prompt()

FALLBACK_RESPONSE = (
    "Unable to reach a decision after multiple attempts. "
    "Please try again or contact IT support."
)


@dataclass
class AgentResult:
    """Outcome of one request: draft, trace, and the routed decision."""

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
    trace: Trace | None = None,
) -> AgentResult:
    """Run one request through the pipeline.

    llm and mcp are seams for tests: pass a FakeLLM and a FakeMCP to run the
    loop without Ollama or a live server. Production callers pass neither.
    Pass trace to listen as steps are recorded; otherwise a fresh Trace is used.
    """
    llm = llm or OllamaClient.from_env()
    if mcp is not None:
        return anyio.run(_react_loop, request, llm, mcp, max_iterations, trace)
    return anyio.run(_react_loop_live, request, llm, max_iterations, trace)


def _note_result(
    name: str,
    observation: Any,
    investigated: set[str],
    employee_info: dict[str, Any] | None,
    decision: str | None,
    rule: str | None,
    flagged: bool,
    review_id: str | None,
    trace: Trace,
) -> tuple[dict[str, Any] | None, str | None, str | None, bool, str | None]:
    """Apply one tool result to the case state. Returns the updated fields."""
    succeeded = _investigation_succeeded(name, observation)
    if succeeded:
        investigated.add(name)
    if name == "get_employee_info" and succeeded and isinstance(observation, dict):
        employee_info = observation
        if _subject_unresolved(employee_info):
            decision = "escalate"
            rule = "subject_unresolved"
            trace.add("route", f"escalate (subject_unresolved) -> {_ROUTES['escalate']}")
    if name == "evaluate_request" and succeeded and isinstance(observation, dict):
        decision = observation.get("decision")
        rule = observation.get("rule")
        if decision:
            trace.add("route", f"{decision} ({rule}) -> {_ROUTES.get(decision, 'unknown route')}")
    if name == "flag_for_human_review" and isinstance(observation, dict) and "error" not in observation:
        flagged = True
        review_id = observation.get("review_id")
    return employee_info, decision, rule, flagged, review_id


def _record_refusal(
    trace: Trace,
    messages: list[dict[str, Any]],
    thought: str,
    action: Any,
    arguments: dict[str, Any],
    observation: dict[str, str],
) -> None:
    """Log a refused call as an action and an observation. Do not coach the model."""
    payload = action.to_dict()
    payload["function"]["arguments"] = arguments
    trace.add("action", f"{action.name}({json.dumps(arguments, sort_keys=True, default=str)})")
    encoded = json.dumps(observation, sort_keys=True)
    trace.add("observation", encoded)
    messages.append({"role": "assistant", "content": thought, "tool_calls": [payload]})
    messages.append({"role": "tool", "content": encoded, "tool_call_id": action.id})


async def _react_loop_live(
    request: str, llm: Any, max_iterations: int, trace: Trace | None = None
) -> AgentResult:
    """Open a live MCP session and run the TAO loop against it."""
    async with MCPClient() as server:
        return await _react_loop(request, llm, server, max_iterations, trace)


async def _react_loop(
    request: str, llm: Any, mcp: Any, max_iterations: int, trace: Trace | None = None
) -> AgentResult:
    """Thought/action/observation loop, then the reflector, for one request."""
    trace = trace or Trace()
    tools = await mcp.list_tool_schemas()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": request},
    ]
    decision: str | None = None
    rule: str | None = None
    review_id: str | None = None
    investigated: set[str] = set()
    employee_info: dict[str, Any] | None = None
    flagged = False
    mentioned = _mentioned_employee(request)
    if mentioned is None:
        decision = "escalate"
        rule = "subject_unresolved"
        trace.add("route", f"escalate (subject_unresolved) -> {_ROUTES['escalate']}")

    for iteration in range(1, max_iterations + 1):
        response = llm.chat(messages, tools=tools)

        if response.has_tool_call and response.tool_call:
            action = response.tool_call
            thought = response.content or f"I need to call {action.name}."
            trace.add("thought", f"(iteration {iteration}) {thought}")
            arguments = {key: as_text(value) for key, value in action.arguments.items()}
            next_needed = _next_step(investigated, employee_info, decision, flagged, mentioned is not None)
            if action.name == "get_employee_info" and mentioned:
                arguments["employee_id"] = mentioned
            if next_needed and action.name != next_needed:
                _record_refusal(
                    trace,
                    messages,
                    thought,
                    action,
                    arguments,
                    {"error": f"{next_needed} has not returned"},
                )
                continue
            if action.name == "flag_for_human_review" and decision != "escalate":
                _record_refusal(
                    trace,
                    messages,
                    thought,
                    action,
                    arguments,
                    {"error": "the decision is not escalate"},
                )
                continue
            if action.name == "evaluate_request":
                arguments, problem = _prepare_evaluate(arguments, request, employee_info)
                if problem:
                    _record_refusal(trace, messages, thought, action, arguments, {"error": problem})
                    continue
            trace.add(
                "action", f"{action.name}({json.dumps(arguments, sort_keys=True, default=str)})"
            )
            try:
                observation = await mcp.call_tool(action.name, arguments)
            except (RuntimeError, json.JSONDecodeError, ValidationError) as error:
                observation = {"error": str(error)}
            trace.add("observation", json.dumps(observation, sort_keys=True, default=str))

            employee_info, decision, rule, flagged, review_id = _note_result(
                action.name,
                observation,
                investigated,
                employee_info,
                decision,
                rule,
                flagged,
                review_id,
                trace,
            )

            payload = action.to_dict()
            payload["function"]["arguments"] = arguments
            messages.append({"role": "assistant", "content": thought, "tool_calls": [payload]})
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

        pending = _next_step(investigated, employee_info, decision, flagged, mentioned is not None)
        if pending:
            arguments = _arguments_for_step(pending, request, employee_info, mentioned)
            if arguments is None:
                observation = {"error": f"{pending} has not returned"}
                trace.add("observation", json.dumps(observation))
                messages.append({"role": "assistant", "content": draft})
                messages.append(
                    {
                        "role": "user",
                        "content": json.dumps(observation) + f" Call {pending} now.",
                    }
                )
                continue
            # The reply arrived before the open step. The loop takes that action.
            thought = f"The reply is early. Calling {pending}."
            trace.add("thought", f"(iteration {iteration}) {thought}")
            trace.add("action", f"{pending}({json.dumps(arguments, sort_keys=True)})")
            try:
                observation = await mcp.call_tool(pending, arguments)
            except (RuntimeError, json.JSONDecodeError, ValidationError) as error:
                observation = {"error": str(error)}
            encoded = json.dumps(observation, sort_keys=True, default=str)
            trace.add("observation", encoded)
            employee_info, decision, rule, flagged, review_id = _note_result(
                pending,
                observation,
                investigated,
                employee_info,
                decision,
                rule,
                flagged,
                review_id,
                trace,
            )
            call = ToolCall(id=f"loop_{iteration}", name=pending, arguments=arguments)
            messages.append({"role": "assistant", "content": thought, "tool_calls": [call.to_dict()]})
            messages.append({"role": "tool", "content": encoded, "tool_call_id": call.id})
            continue

        trace.add("draft", draft)
        reflection_result = reflect(draft, trace, llm, request)
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
