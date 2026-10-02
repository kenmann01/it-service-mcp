"""Role eligibility and the period that covers each item."""

from typing import NotRequired, TypedDict

from tools.data_store import load_policy_limits


class ItemLimit(TypedDict):
    eligible: bool
    period: str


class PolicyLimits(TypedDict):
    role: str
    known: bool
    eligible_for: NotRequired[list[str]]
    items: NotRequired[dict[str, ItemLimit]]


def get_policy_limits(role: str) -> PolicyLimits:
    """Return what a role is eligible for and the period for each item."""
    key = role.strip().lower()
    limits = load_policy_limits()
    if key not in limits:
        return {"role": key, "known": False}
    items: dict[str, ItemLimit] = limits[key]
    eligible_for = [item for item, rule in items.items() if rule["eligible"]]
    return {
        "role": key,
        "known": True,
        "eligible_for": eligible_for,
        "items": items,
    }
