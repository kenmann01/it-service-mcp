"""The 16-rule decision procedure from docs/requirements.md, as pure functions.

The request is consumed exactly as submitted: the claimed role is not
cross-checked against employee data, and equipment on file is not consulted.
"""

from typing import TypedDict

ROLES = ("employee", "manager", "director")
ITEMS = ("headphones", "phone", "laptop")

_WEEK_OVERLAP_SIGNALS = ("keep both", "both laptops")
_WEEK_SIGNALS = ("week", "7 days")
_RETURN_SIGNALS = ("return",)
_SECOND_SIGNALS = ("second", "spare", "additional", "another", "extra", "already have")
_FIRST_SIGNALS = ("first", "do not have", "don't have", "not have one yet")
_REPLACEMENT_SIGNALS = (
    "replacement",
    "replace",
    "replacing",
    "broken",
    "broke",
    "lost",
    "stolen",
    "worn out",
    "stopped working",
)


class Decision(TypedDict):
    """The decision and rule id returned by the 16-rule procedure."""

    decision: str
    rule: str


def classify_reason(reason: str) -> str:
    """Return the reason class: the first of the spec's classes that matches."""
    text = reason.strip().lower()
    overlap = any(s in text for s in _WEEK_OVERLAP_SIGNALS)
    week = any(s in text for s in _WEEK_SIGNALS)
    returns = any(s in text for s in _RETURN_SIGNALS)
    if overlap and week and returns:
        return "week_overlap"
    has_second = any(s in text for s in _SECOND_SIGNALS)
    has_first = any(s in text for s in _FIRST_SIGNALS)
    if has_second and has_first:
        return "unclear"
    if has_second:
        return "second"
    if has_first:
        return "first"
    if any(s in text for s in _REPLACEMENT_SIGNALS):
        return "replacement"
    return "unclear"


def _blank(*fields: str) -> bool:
    """True when any field is missing or only whitespace."""
    return any(not str(field).strip() for field in fields)


def evaluate_request(employee: str, role: str, item_requested: str, reason: str) -> Decision:
    """Apply the 16-rule first-match procedure to one request.

    Returns {"decision": "approve"|"deny"|"escalate", "rule": "<id>"}. An
    `escalate` decision means a human should decide; call flag_for_human_review.
    """
    if _blank(employee, role, item_requested, reason):
        return {"decision": "escalate", "rule": "blank_field"}

    normalized_role = role.strip().lower()
    normalized_item = item_requested.strip().lower()
    if normalized_role not in ROLES:
        return {"decision": "escalate", "rule": "unknown_role"}
    if normalized_item not in ITEMS:
        return {"decision": "escalate", "rule": "unknown_item"}

    reason_class = classify_reason(reason)
    laptop = normalized_item == "laptop"
    phone = normalized_item == "phone"
    headphones = normalized_item == "headphones"
    staff = normalized_role in ("manager", "director")

    if laptop and normalized_role == "employee":
        return {"decision": "deny", "rule": "employee_laptop"}
    if laptop and staff and reason_class == "week_overlap":
        return {"decision": "escalate", "rule": "laptop_week_overlap"}
    if laptop:
        return {"decision": "deny", "rule": "laptop_not_covered"}

    if headphones and reason_class == "replacement":
        return {"decision": "approve", "rule": "headphones_replacement"}
    if headphones and reason_class == "first":
        return {"decision": "approve", "rule": "headphones_first"}
    if headphones and reason_class == "second":
        return {"decision": "deny", "rule": "headphones_second"}

    if phone and normalized_role == "employee" and reason_class == "replacement":
        return {"decision": "approve", "rule": "employee_phone_replacement"}
    if phone and normalized_role == "employee" and reason_class == "first":
        return {"decision": "escalate", "rule": "employee_phone_first"}
    if phone and normalized_role == "employee" and reason_class == "second":
        return {"decision": "deny", "rule": "employee_phone_second"}
    if phone and staff and reason_class == "replacement":
        return {"decision": "approve", "rule": "manager_phone_replacement"}
    if phone and staff and reason_class == "first":
        return {"decision": "approve", "rule": "manager_phone_first"}
    if phone and staff and reason_class == "second":
        return {"decision": "deny", "rule": "manager_phone_second"}

    # Rule 16: headphones or phone with an unclear or week_overlap reason class.
    return {"decision": "escalate", "rule": "unclear_reason"}
