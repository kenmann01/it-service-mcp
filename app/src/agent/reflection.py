"""Reflector: a second LLM pass that confirms or corrects the draft."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.trace import Trace

REFLECTION_PROMPT = """You are a policy compliance reviewer for IT equipment requests.

DRAFT RESPONSE:
{draft}

TOOL OBSERVATIONS (from the ReAct trace):
{observations}

Check the draft against the observations:
1. Is the draft an actual message to the requester? If it is a note about drafting, or mentions tools, iterations, or routing, that is a failure: correct it into a proper message.
2. Does it claim anything the observations do not support?
3. Does it state the decision and rule exactly as the evaluate_request tool returned them?
4. If the request was escalated, does the handoff mention the review id and the real reason?
5. Does it commit to anything (approval, refusal) the data does not clearly support?

If the draft is accurate, reply exactly: CONFIRMED
If the draft needs fixing, reply exactly: CORRECTED: <the revised draft>
"""


@dataclass
class ReflectionResult:
    """Whether the reflector kept the draft and the text that should be sent."""

    confirmed: bool
    final_draft: str
    original: str
    summary: str


def reflect(draft: str, trace: Trace, llm: Any) -> ReflectionResult:
    """Review the draft against the trace's observations; fail open to confirmed."""
    prompt = REFLECTION_PROMPT.format(draft=draft, observations=trace.observations() or "(none)")
    response = llm.chat([{"role": "user", "content": prompt}])
    text = (response.content or "").strip()

    if text.startswith("CORRECTED:"):
        revised = text.removeprefix("CORRECTED:").strip() or draft
        return ReflectionResult(False, revised, draft, f"Draft corrected: {revised}")
    if text.startswith("CONFIRMED"):
        return ReflectionResult(True, draft, draft, "Draft confirmed against tool observations")
    return ReflectionResult(True, draft, draft, "Reflection reply was not parseable; draft kept")
