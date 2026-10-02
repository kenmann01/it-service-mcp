"""Reflector: a second LLM pass that confirms or corrects the draft."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent.trace import Trace

_NUMBER_RE = re.compile(r"\d+")

REFLECTION_PROMPT = """You are a policy compliance reviewer for IT equipment requests.

REQUEST:
{request}

DRAFT RESPONSE:
{draft}

TOOL OBSERVATIONS (from the ReAct trace):
{observations}

Check the draft against the observations:
1. Is the draft an actual message to the requester? If it is a note about drafting, or mentions tools, iterations, or routing, that is a failure: correct it into a proper message.
2. Does it claim anything the observations do not support?
3. Does it state the decision and rule exactly as the route, or evaluate_request, returned them? A subject_unresolved route means the id is not on file.
4. Does it contradict get_policy_limits or check_request_eligibility? If those observations say the item is not covered, or the role is not known, the draft must not claim the opposite.
5. Does it invent a quantity, count, name, or detail that the request and the observations do not contain? A number of items that was never stated is a failure. A person's name that is not in the request or the observations is a failure.
6. If the request was escalated, does the handoff mention the review id and the real reason?
7. Does it commit to anything (approval, refusal) the data does not clearly support?

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


def unsupported_numbers(text: str, *sources: str) -> list[str]:
    """Return digit groups in text that appear in none of the sources."""
    allowed = "\n".join(sources)
    found: list[str] = []
    for number in _NUMBER_RE.findall(text):
        if number not in allowed and number not in found:
            found.append(number)
    return found


def _strip_numbers(text: str, numbers: list[str]) -> str:
    """Drop unsupported counts so they cannot be filed in the letter."""
    cleaned = text
    for number in numbers:
        cleaned = re.sub(rf"\b{re.escape(number)}\b", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" +([,.])", r"\1", cleaned)
    return cleaned.strip()


def reflect(draft: str, trace: Trace, llm: Any, request: str = "") -> ReflectionResult:
    """Review the draft against the request and the trace; drop unstated counts."""
    observations = trace.observations() or "(none)"
    prompt = REFLECTION_PROMPT.format(
        draft=draft,
        request=request or "(not provided)",
        observations=observations,
    )
    response = llm.chat([{"role": "user", "content": prompt}])
    text = (response.content or "").strip()

    if text.startswith("CORRECTED:"):
        final = text.removeprefix("CORRECTED:").strip() or draft
        confirmed = False
        summary = f"Draft corrected: {final}"
    elif text.startswith("CONFIRMED"):
        final = draft
        confirmed = True
        summary = "Draft confirmed against tool observations"
    else:
        final = draft
        confirmed = True
        summary = "Reflection reply was not parseable; draft kept"

    stray = unsupported_numbers(final, request, observations)
    if stray:
        listed = ", ".join(stray)
        retry = llm.chat(
            [
                {
                    "role": "user",
                    "content": (
                        f"The number {listed} is not in the request or the observations. "
                        "Reply exactly: CORRECTED: <the revised draft with that number removed>\n\n"
                        f"REQUEST:\n{request or '(not provided)'}\n\nDRAFT:\n{final}"
                    ),
                }
            ]
        )
        retry_text = (retry.content or "").strip()
        if retry_text.startswith("CORRECTED:"):
            final = retry_text.removeprefix("CORRECTED:").strip() or final
        still = unsupported_numbers(final, request, observations)
        if still:
            final = _strip_numbers(final, still)
            summary = f"Removed unstated quantity {', '.join(still)}: {final}"
        else:
            summary = f"Draft corrected: {final}"
        confirmed = False

    return ReflectionResult(confirmed, final, draft, summary)
