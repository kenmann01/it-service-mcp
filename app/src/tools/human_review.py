"""Process-local queue of requests escalated for a person to review."""

from typing import TypedDict

_reviews: list["ReviewRecord"] = []


class ReviewRecord(TypedDict):
    """One escalated request waiting for a person to decide."""

    review_id: str
    employee_id: str
    request: str
    reason: str
    status: str


def flag_for_human_review(employee_id: str, request: str, reason: str) -> ReviewRecord:
    """Escalate a request for human review. This records the request and never approves it."""
    record: ReviewRecord = {
        "review_id": f"R{len(_reviews) + 1:03d}",
        "employee_id": employee_id,
        "request": request,
        "reason": reason,
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
