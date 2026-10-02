"""Checks of the 16-rule decision procedure and the reason classifier."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tools.decision import classify_reason, evaluate_request

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "mock-requests.json"


class ClassifyReasonTests(unittest.TestCase):
    def test_each_signal_class(self) -> None:
        self.assertEqual(classify_reason("Second pair, I already have one."), "second")
        self.assertEqual(classify_reason("First pair, I do not have headphones."), "first")
        self.assertEqual(classify_reason("Replacement of my broken headphones."), "replacement")

    def test_week_overlap_needs_all_three_signals(self) -> None:
        self.assertEqual(
            classify_reason("Keep both for a week, then return the old one."), "week_overlap"
        )
        self.assertEqual(classify_reason("Keep both laptops, they are great."), "unclear")
        self.assertEqual(classify_reason("Return it next week."), "unclear")

    def test_week_overlap_beats_replacement(self) -> None:
        reason = "Replacing my laptop. I will keep both for a week before I return the old one."
        self.assertEqual(classify_reason(reason), "week_overlap")

    def test_second_plus_first_is_unclear(self) -> None:
        self.assertEqual(classify_reason("A second pair since I do not have one."), "unclear")

    def test_unrecognized_reason_is_unclear(self) -> None:
        self.assertEqual(classify_reason("Protein goals."), "unclear")

    def test_matching_ignores_case_and_outer_spaces(self) -> None:
        self.assertEqual(classify_reason("  It BROKE. Need a REPLACEMENT.  "), "replacement")


class EvaluateRequestTests(unittest.TestCase):
    def test_blank_field_escalates(self) -> None:
        self.assertEqual(
            evaluate_request("Grace Hopper", "employee", "headphones", "  "),
            {"decision": "escalate", "rule": "blank_field"},
        )
        self.assertEqual(
            evaluate_request("  ", "employee", "headphones", "broken"),
            {"decision": "escalate", "rule": "blank_field"},
        )

    def test_unknown_role_escalates(self) -> None:
        self.assertEqual(
            evaluate_request("Mani", "FDE", "vanilla latte", "protein goals"),
            {"decision": "escalate", "rule": "unknown_role"},
        )
        self.assertEqual(
            evaluate_request("Mani", "executive", "headphones", "replacement"),
            {"decision": "escalate", "rule": "unknown_role"},
        )

    def test_unknown_item_escalates(self) -> None:
        self.assertEqual(
            evaluate_request("Grace Hopper", "employee", "monitor", "replacement"),
            {"decision": "escalate", "rule": "unknown_item"},
        )

    def test_employee_laptop_is_denied(self) -> None:
        self.assertEqual(
            evaluate_request("Linus Torvalds", "employee", "laptop", "I need it for work."),
            {"decision": "deny", "rule": "employee_laptop"},
        )

    def test_manager_laptop_week_overlap_escalates(self) -> None:
        reason = "Replacing my laptop. I will keep both for a week before returning the old one."
        self.assertEqual(
            evaluate_request("Ada Lovelace", "manager", "laptop", reason),
            {"decision": "escalate", "rule": "laptop_week_overlap"},
        )

    def test_other_manager_laptops_are_denied(self) -> None:
        self.assertEqual(
            evaluate_request("Ada Lovelace", "director", "laptop", "broken screen"),
            {"decision": "deny", "rule": "laptop_not_covered"},
        )

    def test_headphones_replacement_and_first_are_approved(self) -> None:
        self.assertEqual(
            evaluate_request("Grace Hopper", "employee", "headphones", "broken"),
            {"decision": "approve", "rule": "headphones_replacement"},
        )
        self.assertEqual(
            evaluate_request("Alan Turing", "manager", "headphones", "first pair"),
            {"decision": "approve", "rule": "headphones_first"},
        )

    def test_headphones_second_is_denied(self) -> None:
        self.assertEqual(
            evaluate_request("Margaret Hamilton", "director", "headphones", "spare pair"),
            {"decision": "deny", "rule": "headphones_second"},
        )

    def test_employee_phone_rules(self) -> None:
        self.assertEqual(
            evaluate_request("Radia Perlman", "employee", "phone", "my phone broke"),
            {"decision": "approve", "rule": "employee_phone_replacement"},
        )
        self.assertEqual(
            evaluate_request("Radia Perlman", "employee", "phone", "first company phone"),
            {"decision": "escalate", "rule": "employee_phone_first"},
        )
        self.assertEqual(
            evaluate_request("Tim Berners-Lee", "employee", "phone", "additional phone"),
            {"decision": "deny", "rule": "employee_phone_second"},
        )

    def test_manager_and_director_phone_rules(self) -> None:
        self.assertEqual(
            evaluate_request("Barbara Liskov", "manager", "phone", "replacement, it stopped working"),
            {"decision": "approve", "rule": "manager_phone_replacement"},
        )
        self.assertEqual(
            evaluate_request("Barbara Liskov", "manager", "phone", "I do not have one yet"),
            {"decision": "approve", "rule": "manager_phone_first"},
        )
        self.assertEqual(
            evaluate_request("Donald Knuth", "director", "phone", "another phone"),
            {"decision": "deny", "rule": "manager_phone_second"},
        )

    def test_unclear_and_week_overlap_reasons_escalate(self) -> None:
        self.assertEqual(
            evaluate_request("Grace Hopper", "employee", "headphones", "not sure what I need"),
            {"decision": "escalate", "rule": "unclear_reason"},
        )
        reason = "Replacing my phone. I will keep both for a week and return the old one."
        self.assertEqual(
            evaluate_request("Ada Lovelace", "manager", "phone", reason),
            {"decision": "escalate", "rule": "unclear_reason"},
        )

    def test_normalizes_role_item_and_reason(self) -> None:
        self.assertEqual(
            evaluate_request(" Grace Hopper ", " Employee ", " Headphones ", " It BROKE. "),
            {"decision": "approve", "rule": "headphones_replacement"},
        )


class FixtureTests(unittest.TestCase):
    def test_all_fixture_cases_match_expected_decision(self) -> None:
        with FIXTURES.open(encoding="utf-8") as handle:
            cases = json.load(handle)["cases"]
        self.assertEqual(len(cases), 10)
        for case in cases:
            with self.subTest(case_id=case["id"]):
                request = case["request"]
                result = evaluate_request(
                    request["employee"],
                    request["role"],
                    request["item_requested"],
                    request["reason"],
                )
                self.assertEqual(result["decision"], case["expected"], case["id"])


if __name__ == "__main__":
    unittest.main()
