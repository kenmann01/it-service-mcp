"""Process-local queue of requests escalated for a person to review."""

from typing import TypedDict

from tools.intake import RequiredId, ReviewFlag, Text

_reviews: list["ReviewRecord"] = []


class ReviewRecord(TypedDict):
    """One escalated request waiting for a person to decide."""

    review_id: str
    employee_id: str
    request: str
    reason: str
    status: str


def flag_for_human_review(employee_id: RequiredId, request: Text, reason: Text) -> ReviewRecord:
    """Escalate a request for human review. This records the request and never approves it."""
    parsed = ReviewFlag.model_validate(
        {"employee_id": employee_id, "request": request, "reason": reason}
    )
    record: ReviewRecord = {
        "review_id": f"R{len(_reviews) + 1:03d}",
        "employee_id": parsed.employee_id,
        "request": parsed.request,
        "reason": parsed.reason,
        "status": "escalated",
    }
    _reviews.append(record)
    return record


def pending_reviews() -> list[ReviewRecord]:
    """Return a copy of the in-process review queue."""
    return list(_reviews)


def clear_reviews() -> None:
    """Empty the in-process review queue."""
    _reviews.clear()
