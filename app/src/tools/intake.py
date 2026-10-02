"""Strict argument models for the five MCP tools.

NaN, Infinity, and non-text become a blank string, so the tool returns a
normal result instead of an MCP error. evaluate_request then escalates a
blank field. A lookup with a blank id or role misses. Instruction text in a
role or item is still rejected.
"""

from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict

_NON_FINITE = frozenset({"nan", "inf", "infinity", "+inf", "-inf", "+infinity", "-infinity"})


def as_text(value: object) -> str:
    """Return text, collapsing NaN, Infinity, and non-text to a blank string.

    A blank string is a value the tool can answer. Raising here makes the MCP
    call an error, and the agent retries that same call.
    """
    if isinstance(value, str):
        if value.strip().lower() in _NON_FINITE:
            return ""
        return value
    return ""


def _required_stripped(value: object) -> str:
    """An id, stripped. Blank means the lookup misses instead of erroring."""
    return as_text(value).strip()


def _role_or_item(value: object) -> str:
    """A role or item. Instruction text is rejected. NaN is blank."""
    text = as_text(value)
    folded = text.lower()
    if "\n" in text or "\r" in text or "ignore previous" in folded:
        raise ValueError("instruction text is not a role or item")
    return text


def _required_role(value: object) -> str:
    """A role lookup key. Blank means the role is unknown instead of an error."""
    text = _role_or_item(value).strip()
    return text


RequiredId = Annotated[str, BeforeValidator(_required_stripped)]
RequiredRole = Annotated[str, BeforeValidator(_required_role)]
RoleOrItem = Annotated[str, BeforeValidator(_role_or_item)]
Text = Annotated[str, BeforeValidator(as_text)]


class _Strict(BaseModel):
    """No coercion and no extra fields."""

    model_config = ConfigDict(extra="forbid", strict=True)


class EmployeeLookup(_Strict):
    """Arguments for get_employee_info."""

    employee_id: RequiredId


class PolicyLookup(_Strict):
    """Arguments for get_policy_limits."""

    role: RequiredRole


class EligibilityLookup(_Strict):
    """Arguments for check_request_eligibility."""

    employee_id: RequiredId
    item: RoleOrItem


class EvaluateSubmission(_Strict):
    """Arguments for evaluate_request. Blank strings stay blank for the policy."""

    employee: Text
    role: RoleOrItem
    item_requested: RoleOrItem
    reason: Text


class ReviewFlag(_Strict):
    """Arguments for flag_for_human_review."""

    employee_id: RequiredId
    request: Text
    reason: Text
