"""Equipment standard IT-POL-EQ-001, evaluated as a control register.

docs/requirements.md is the source of the sixteen controls. docs/policy.md is
the same standard in the form Internal IT publishes. This module does not add
controls, and it does not consult the employee record or the equipment on file.
The request is decided exactly as submitted.

The register is first-applicable: the evaluator walks the controls in order and
stops at the first one whose applicability matches. That is the combining
algorithm. The function that calls it does not branch on the request.
"""

import re
from dataclasses import dataclass
from typing import TypedDict

from tools.intake import EvaluateSubmission, RoleOrItem, Text

ROLES = ("employee", "manager", "director")
ITEMS = ("headphones", "phone", "laptop")

_STAFF = frozenset({"manager", "director"})
_CATALOG_ROLES = frozenset(ROLES)
_PERSONAL_EQUIPMENT = frozenset({"headphones", "phone"})

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

# A count of items, such as "200 new headphones". "7 days" does not match.
_BULK_COUNT_RE = re.compile(
    r"\b(\d+)\b(?:\s+\w+){0,3}\s+"
    r"(?:headphones|headphone|phones|phone|laptops|laptop|pairs|pair)\b",
    re.IGNORECASE,
)


class Decision(TypedDict):
    """The effect and control id of the first applicable control."""

    decision: str
    rule: str


@dataclass(frozen=True)
class _Request:
    """One request after intake normalization, before any control is applied."""

    employee: str
    role: str
    item: str
    reason_class: str
    blank: bool


@dataclass(frozen=True)
class Control:
    """One control in the register.

    A dimension left as None is not tested. The four flags cover the intake
    gates (completeness, role catalog, asset catalog). Later controls name the
    role band, the asset, and the request type they govern.
    """

    control_id: str
    effect: str
    statement: str
    only_when_blank: bool = False
    role_outside_catalog: bool = False
    item_outside_catalog: bool = False
    roles: frozenset[str] | None = None
    items: frozenset[str] | None = None
    reason_classes: frozenset[str] | None = None


# First-applicable. Do not reorder: a later control is the residual of the
# earlier ones, which is how employee laptops are denied before the laptop
# exception, and how week_overlap is taken before the laptop denial.
CONTROLS: tuple[Control, ...] = (
    Control(
        "blank_field",
        "escalate",
        "A request missing the requester, the role, the asset, or the business reason is incomplete and goes to IT.",
        only_when_blank=True,
    ),
    Control(
        "unknown_role",
        "escalate",
        "A role outside employee, manager, and director is not in this standard and goes to IT.",
        role_outside_catalog=True,
    ),
    Control(
        "unknown_item",
        "escalate",
        "An asset outside headphones, phone, and laptop is not in the catalog and goes to IT.",
        item_outside_catalog=True,
    ),
    Control(
        "employee_laptop",
        "deny",
        "Employees are not issued a laptop under this standard, whatever the reason says.",
        roles=frozenset({"employee"}),
        items=frozenset({"laptop"}),
    ),
    Control(
        "laptop_week_overlap",
        "escalate",
        "A manager or director who will hold two laptops for a week and then return one is an exception for IT.",
        roles=_STAFF,
        items=frozenset({"laptop"}),
        reason_classes=frozenset({"week_overlap"}),
    ),
    Control(
        "laptop_not_covered",
        "deny",
        "No other laptop request is issued under this standard.",
        roles=_STAFF,
        items=frozenset({"laptop"}),
    ),
    Control(
        "headphones_replacement",
        "approve",
        "A replacement headset is issued to an employee, a manager, or a director.",
        roles=_CATALOG_ROLES,
        items=frozenset({"headphones"}),
        reason_classes=frozenset({"replacement"}),
    ),
    Control(
        "headphones_first",
        "approve",
        "A first headset is issued to an employee, a manager, or a director who does not have one.",
        roles=_CATALOG_ROLES,
        items=frozenset({"headphones"}),
        reason_classes=frozenset({"first"}),
    ),
    Control(
        "headphones_second",
        "deny",
        "A second or spare headset, while the current one is kept, is not issued.",
        roles=_CATALOG_ROLES,
        items=frozenset({"headphones"}),
        reason_classes=frozenset({"second"}),
    ),
    Control(
        "employee_phone_replacement",
        "approve",
        "An employee is issued a replacement for a company phone they already have.",
        roles=frozenset({"employee"}),
        items=frozenset({"phone"}),
        reason_classes=frozenset({"replacement"}),
    ),
    Control(
        "employee_phone_first",
        "escalate",
        "Whether an employee receives a first company phone is an exception for IT.",
        roles=frozenset({"employee"}),
        items=frozenset({"phone"}),
        reason_classes=frozenset({"first"}),
    ),
    Control(
        "employee_phone_second",
        "deny",
        "An employee is not issued an additional phone while they keep the current one.",
        roles=frozenset({"employee"}),
        items=frozenset({"phone"}),
        reason_classes=frozenset({"second"}),
    ),
    Control(
        "manager_phone_replacement",
        "approve",
        "A manager or director is issued a replacement for the company phone they have.",
        roles=_STAFF,
        items=frozenset({"phone"}),
        reason_classes=frozenset({"replacement"}),
    ),
    Control(
        "manager_phone_first",
        "approve",
        "A manager or director who does not yet have a company phone is issued one.",
        roles=_STAFF,
        items=frozenset({"phone"}),
        reason_classes=frozenset({"first"}),
    ),
    Control(
        "manager_phone_second",
        "deny",
        "A manager or director is not issued a second phone while they keep the current one.",
        roles=_STAFF,
        items=frozenset({"phone"}),
        reason_classes=frozenset({"second"}),
    ),
    Control(
        "unclear_reason",
        "escalate",
        "A headset or phone request whose reason is unclassified, or is a week-long overlap, goes to IT.",
        roles=_CATALOG_ROLES,
        items=_PERSONAL_EQUIPMENT,
        reason_classes=frozenset({"unclear", "week_overlap"}),
    ),
)


def bulk_item_counts(text: str) -> list[str]:
    """Return item counts greater than one, in the order they appear."""
    counts: list[str] = []
    for match in _BULK_COUNT_RE.finditer(text):
        count = match.group(1)
        if int(count) > 1 and count not in counts:
            counts.append(count)
    return counts


def classify_reason(reason: str) -> str:
    """Return the request type: the first class in the standard that matches."""
    text = reason.strip().lower()
    overlap = any(s in text for s in _WEEK_OVERLAP_SIGNALS)
    week = any(s in text for s in _WEEK_SIGNALS)
    returns = any(s in text for s in _RETURN_SIGNALS)
    if overlap and week and returns:
        return "week_overlap"
    if bulk_item_counts(text):
        return "unclear"
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


def _intake(employee: str, role: str, item_requested: str, reason: str) -> _Request:
    """Normalize one submission the way the standard requires, before controls run."""
    return _Request(
        employee=employee.strip(),
        role=role.strip().lower(),
        item=item_requested.strip().lower(),
        reason_class=classify_reason(reason),
        blank=_blank(employee, role, item_requested, reason),
    )


def _applies(control: Control, request: _Request) -> bool:
    """True when this control governs this request. Dimensions left unset are skipped."""
    if control.only_when_blank:
        return request.blank
    if request.blank:
        return False
    if control.role_outside_catalog:
        return request.role not in _CATALOG_ROLES
    if request.role not in _CATALOG_ROLES:
        return False
    if control.item_outside_catalog:
        return request.item not in ITEMS
    if request.item not in ITEMS:
        return False
    if control.roles is not None and request.role not in control.roles:
        return False
    if control.items is not None and request.item not in control.items:
        return False
    if control.reason_classes is not None and request.reason_class not in control.reason_classes:
        return False
    return True


def evaluate_request(employee: Text, role: RoleOrItem, item_requested: RoleOrItem, reason: Text) -> Decision:
    """Apply IT-POL-EQ-001 and return the effect of the first matching control.

    Returns {"decision": "approve"|"deny"|"escalate", "rule": "<control id>"}.
    approve means the standard covers the request. deny means it does not.
    escalate means the request is incomplete or an exception; call
    flag_for_human_review so a person decides.
    """
    parsed = EvaluateSubmission.model_validate(
        {
            "employee": employee,
            "role": role,
            "item_requested": item_requested,
            "reason": reason,
        }
    )
    request = _intake(parsed.employee, parsed.role, parsed.item_requested, parsed.reason)
    for control in CONTROLS:
        if _applies(control, request):
            return {"decision": control.effect, "rule": control.control_id}
    raise RuntimeError("IT-POL-EQ-001 has no applicable control for this request")
