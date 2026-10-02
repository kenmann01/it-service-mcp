"""Isolated checks of the IT tools against the JSON mock data. No MCP transport."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tools.eligibility import check_request_eligibility
from tools.employee_info import get_employee_info
from tools.human_review import clear_reviews, flag_for_human_review
from tools.policy_limits import get_policy_limits


class EmployeeInfoTests(unittest.TestCase):
    def test_known_employee(self) -> None:
        info = get_employee_info("E001")
        self.assertTrue(info["found"])
        self.assertEqual(info["name"], "Grace Hopper")
        self.assertEqual(info["role"], "employee")
        self.assertEqual(info["tenure_years"], 14)
        self.assertEqual(info["equipment"], ["headphones", "laptop"])

    def test_strips_id_whitespace(self) -> None:
        info = get_employee_info("  E010 ")
        self.assertTrue(info["found"])
        self.assertEqual(info["name"], "Linus Torvalds")
        self.assertEqual(info["role"], "employee")

    def test_unknown_employee(self) -> None:
        info = get_employee_info("E999")
        self.assertEqual(info, {"found": False, "employee_id": "E999"})


class PolicyLimitTests(unittest.TestCase):
    def test_each_role(self) -> None:
        for role in ("employee", "manager", "director"):
            limits = get_policy_limits(role)
            self.assertTrue(limits["known"])
            self.assertEqual(limits["eligible_for"], ["headphones", "phone"])
            self.assertFalse(limits["items"]["laptop"]["eligible"])
            self.assertIn("period", limits["items"]["headphones"])

    def test_employee_phone_period_is_replacement_only(self) -> None:
        limits = get_policy_limits(" Employee ")
        self.assertEqual(limits["role"], "employee")
        self.assertIn("replacement", limits["items"]["phone"]["period"].lower())
        self.assertNotIn("year", limits["items"]["phone"]["period"].lower())

    def test_manager_phone_covers_a_first_phone(self) -> None:
        period = get_policy_limits("manager")["items"]["phone"]["period"].lower()
        self.assertIn("first", period)
        self.assertIn("second", period)

    def test_unknown_role(self) -> None:
        limits = get_policy_limits("executive")
        self.assertEqual(limits, {"role": "executive", "known": False})


class EligibilityTests(unittest.TestCase):
    def test_headphones_are_eligible_for_every_role(self) -> None:
        for employee_id in ("E001", "E003", "E004"):
            result = check_request_eligibility(employee_id, " Headphones ")
            self.assertTrue(result["eligible"])
            self.assertEqual(result["item"], "headphones")

    def test_phone_is_eligible_for_every_role(self) -> None:
        for employee_id in ("E005", "E007", "E013"):
            result = check_request_eligibility(employee_id, "phone")
            self.assertTrue(result["eligible"])

    def test_laptop_is_never_eligible(self) -> None:
        for employee_id in ("E010", "E009", "E008"):
            result = check_request_eligibility(employee_id, "laptop")
            self.assertFalse(result["eligible"])

    def test_unknown_item_and_unknown_employee(self) -> None:
        self.assertFalse(check_request_eligibility("E001", "monitor")["eligible"])
        self.assertFalse(check_request_eligibility("E999", "headphones")["eligible"])

    def test_does_not_use_equipment_on_file(self) -> None:
        without_headphones = check_request_eligibility("E011", "headphones")
        with_headphones = check_request_eligibility("E001", "headphones")
        self.assertTrue(without_headphones["eligible"])
        self.assertTrue(with_headphones["eligible"])


class HumanReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_reviews()

    def test_two_escalations_get_distinct_ids(self) -> None:
        first = flag_for_human_review("E010", "laptop", "I need a laptop for my work.")
        second = flag_for_human_review("E004", "headphones", "Second pair.")
        self.assertEqual(first["status"], "escalated")
        self.assertEqual(second["status"], "escalated")
        self.assertNotEqual(first["review_id"], second["review_id"])
        self.assertEqual(first["employee_id"], "E010")
        self.assertEqual(second["request"], "headphones")

    def test_blank_fields_are_still_escalated(self) -> None:
        record = flag_for_human_review("  ", "  ", "  ")
        self.assertEqual(record["status"], "escalated")
        self.assertEqual(record["request"], "  ")


if __name__ == "__main__":
    unittest.main()
