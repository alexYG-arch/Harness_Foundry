"""Production accounting is separate from new checker-only rounds, not history."""
import unittest

from harness_foundry_factory.build_state import (
    attempt_budget, is_checker_reverification, production_attempts, repair_budget_exhaustion,
)


class CorrectionBudgetTests(unittest.TestCase):
    def rows(self):
        return [
            {"attempt_id": "production", "workpack_id": "MAKE"},
            {"attempt_id": "historical-check", "workpack_id": "MAKE",
             "reverification_of_attempt_id": "production"},
            {"attempt_id": "new-check", "workpack_id": "MAKE",
             "reverification_of_attempt_id": "production",
             "reverify_kind": "SAME_SCOPE_CHECKER_REVERIFY_V1", "production_budget_charge": 0},
        ]

    def test_old_reverification_stays_charged_new_round_separate(self):
        rows = self.rows()
        budget = attempt_budget({"max_attempts": 3, "max_task_attempts": 3}, rows)
        self.assertEqual(budget["attempts_consumed"], 2)
        self.assertEqual(budget["task_attempts_consumed"], {"MAKE": 2})
        self.assertEqual(budget["attempts_remaining"], 1)
        self.assertEqual(budget["checker_reverification_rounds"], 1)
        self.assertEqual(len(rows), 3, "history must remain complete")

    def test_partial_or_unknown_markers_never_refund_production(self):
        row = self.rows()[-1]
        for field in ("reverification_of_attempt_id", "reverify_kind", "production_budget_charge"):
            changed = {k: v for k, v in row.items() if k != field}
            self.assertFalse(is_checker_reverification(changed))
            self.assertEqual(production_attempts([changed]), [changed])
        self.assertFalse(is_checker_reverification({**row, "reverify_kind": "OTHER"}))

    def test_repair_can_use_original_last_production_allowance(self):
        rows = {row["attempt_id"]: row for row in self.rows()}
        prepared = {"scope": {"max_attempts": 3, "max_task_attempts": 3},
                    "task_budget_owners": {"MAKE": ["MAKE"]}}
        self.assertIsNone(repair_budget_exhaustion(prepared, rows, {"MAKE"}))
        rows["last-production"] = {"attempt_id": "last-production", "workpack_id": "MAKE"}
        self.assertEqual(repair_budget_exhaustion(prepared, rows, {"MAKE"})["status"],
                         "TASK_REPAIR_BUDGET_EXHAUSTED")


if __name__ == "__main__":
    unittest.main()
