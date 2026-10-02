"""Whether a role may receive an item under at least one covered reason."""

from typing import TypedDict

from tools.employee_info import get_employee_info
from tools.policy_limits import get_policy_limits


class Eligibility(TypedDict):
    employee_id: str
    item: str
    eligible: bool


def check_request_eligibility(employee_id: str, item: str) -> Eligibility:
    """Return whether this employee's role may request this item under policy.

    True only when the role is covered for the item under at least one reason
    class. A laptop, an unknown item, or an unknown employee is not eligible.
    Equipment already on file is not consulted, and the reason text is not
    classified here.
    """
    info = get_employee_info(employee_id)
    normalized = item.strip().lower()
    if not info["found"]:
        return {"employee_id": info["employee_id"], "item": normalized, "eligible": False}
    limits = get_policy_limits(info["role"])
    items = limits.get("items") or {}
    rule = items.get(normalized)
    eligible = bool(limits["known"] and rule is not None and rule["eligible"])
    return {"employee_id": info["employee_id"], "item": normalized, "eligible": eligible}
