"""Look up role, tenure, and equipment for one employee."""

from typing import NotRequired, TypedDict

from tools.data_store import load_employees
from tools.intake import EmployeeLookup, RequiredId


class EmployeeInfo(TypedDict):
    """Role, tenure, and equipment on file, or a found=false miss."""

    found: bool
    employee_id: str
    name: NotRequired[str]
    role: NotRequired[str]
    tenure_years: NotRequired[int]
    equipment: NotRequired[list[str]]


def get_employee_info(employee_id: RequiredId) -> EmployeeInfo:
    """Return role, tenure, and current equipment on file for an employee."""
    key = EmployeeLookup.model_validate({"employee_id": employee_id}).employee_id
    for employee in load_employees():
        if employee["employee_id"] == key:
            return {
                "found": True,
                "employee_id": employee["employee_id"],
                "name": employee["name"],
                "role": employee["role"],
                "tenure_years": employee["tenure_years"],
                "equipment": list(employee["equipment"]),
            }
    return {"found": False, "employee_id": key}
