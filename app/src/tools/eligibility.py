"""Whether a role may receive an item under at least one covered reason."""

from typing import TypedDict

from tools.employee_info import get_employee_info
from tools.intake import EligibilityLookup, RequiredId, RoleOrItem
from tools.policy_limits import get_policy_limits


class Eligibility(TypedDict):
    """Whether one employee may request one item under policy."""

    employee_id: str
    item: str
    eligible: bool


def check_request_eligibility(employee_id: RequiredId, item: RoleOrItem) -> Eligibility:
    """Return whether this employee's role may request this item under policy.

    True only when the role is covered for the item under at least one reason
    class. A laptop, an unknown item, or an unknown employee is not eligible.
    Equipment already on file is not consulted, and the reason text is not
    classified here.
    """
    parsed = EligibilityLookup.model_validate({"employee_id": employee_id, "item": item})
    info = get_employee_info(parsed.employee_id)
    normalized = parsed.item.strip().lower()
    if not info["found"]:
        return {"employee_id": info["employee_id"], "item": normalized, "eligible": False}
    limits = get_policy_limits(info["role"])
    items = limits.get("items") or {}
    rule = items.get(normalized)
    eligible = bool(limits["known"] and rule is not None and rule["eligible"])
    return {"employee_id": info["employee_id"], "item": normalized, "eligible": eligible}
