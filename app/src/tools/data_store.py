"""Load the synthetic employee and policy JSON used by the IT tools."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@lru_cache(maxsize=1)
def load_employees() -> tuple[dict[str, Any], ...]:
    payload = json.loads((DATA_DIR / "employees.json").read_text(encoding="utf-8"))
    return tuple(payload["employees"])


@lru_cache(maxsize=1)
def load_policy_limits() -> dict[str, Any]:
    return json.loads((DATA_DIR / "policy_limits.json").read_text(encoding="utf-8"))
