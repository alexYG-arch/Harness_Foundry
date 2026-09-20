"""Plan adaptation preserves the external contract, ownership and real budgets."""

from copy import deepcopy
import unittest

from harness_foundry_factory.build_authoring import record_build_plan_proposal
from harness_foundry_factory.build_plan import validate_build_plan
from harness_foundry_factory.build_replan import adapt_build_plan
from harness_foundry_factory.build_types import RequestValidationError
import test_build_runtime as support


class BuildReplanTests(unittest.TestCase):
    def setUp(self):
        self.f = support.BuildRuntimeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        for task in self.f.plan["workpacks"]:
            task["job_id"] = "DATA"
            self.f.scope["task_write_roots"][task["workpack_id"]] = ["src", "outputs"]
        self.original = deepcopy(self.f.plan)

    def merged(self, plan=None):
        plan = deepcopy(plan or self.original)
        first, second = plan["workpacks"]
        first["workpack_id"] = "COMBINED"
        first["atom_ids"] += second["atom_ids"]
        first["artifacts"] += second["artifacts"]
        first["verification"] += second["verification"]
        first["local_argv"][-1] += "; " + second["local_argv"][-1]
        plan["workpacks"] = [first]
        plan["revision"] += 1
        return plan

    def record(self, plan):
        return record_build_plan_proposal(self.f.store, self.f.ir, plan, document_review=self.f.review,
                                         **self.f.kwargs("replan-" + str(plan["revision"])))

    def test_merge_executes_once_checks_all_original_cases_and_keeps_one_approval(self):
        self.f.prepare()
        merged = self.merged()
        validate_build_plan(self.f.ir, merged)
        self.record(merged)
        self.assertEqual(self.f.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(self.f.events("BUILD_AUTHORIZATION_APPROVED")), 1)
        attempts = self.f.events("BUILD_ATTEMPT_STARTED")
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["payload"]["budget_workpack_ids"], ["IMPLEMENT-READER", "MAKE-REPORT"])
        self.assertEqual(len(self.f.runner.invocations), 4)
        self.assertEqual(self.f.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(self.f.runner.invocations), 4)

    def prepare_split(self, *, max_task_attempts=3):
        self.f.plan.clear()
        self.f.plan.update(self.merged())
        self.f.plan["revision"] = 1
        self.f.scope["task_write_roots"] = {"COMBINED": ["src", "outputs"]}
        self.f.scope["max_task_attempts"] = max_task_attempts
        self.f.prepare()
        split = deepcopy(self.original)
        split["revision"] = 2
        self.record(split)
        return split

    def test_split_retains_external_outputs_and_charges_original_task_budget(self):
        self.prepare_split()
        self.assertEqual(self.f.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual([e["payload"]["budget_workpack_ids"] for e in self.f.events("BUILD_ATTEMPT_STARTED")],
                         [["COMBINED"], ["COMBINED"]])
        self.assertEqual(len(self.f.events("BUILD_AUTHORIZATION_APPROVED")), 1)

    def test_split_cannot_multiply_the_approved_per_task_budget(self):
        self.prepare_split(max_task_attempts=1)
        self.assertEqual(self.f.advance()["status"], "TASK_REPAIR_BUDGET_EXHAUSTED")
        self.assertEqual(len(self.f.events("BUILD_ATTEMPT_STARTED")), 1)
        self.assertEqual(self.f.advance()["status"], "TASK_REPAIR_BUDGET_EXHAUSTED")
        self.assertFalse((self.f.workspace / "outputs/summary.json").exists())

    def test_started_task_identity_is_fixed_independent_of_final_status(self):
        revised = deepcopy(self.original)
        revised["workpacks"][0]["workpack_id"] = "RENAMED"
        revised["workpacks"][1]["depends_on"] = ["RENAMED"]
        validate_build_plan(self.f.ir, revised)
        with self.assertRaisesRegex(RequestValidationError, "started task"):
            adapt_build_plan(self.original, revised, self.f.scope, [self.original["workpacks"][0]])

    def test_controller_rejects_renaming_after_a_real_rejected_attempt(self):
        self.f.plan["workpacks"][0]["local_argv"][-1] = "pass"
        self.f.scope["max_task_attempts"] = 1
        self.f.prepare()
        self.assertEqual(self.f.advance()["status"], "TASK_REPAIR_BUDGET_EXHAUSTED")
        revised = deepcopy(self.f.plan)
        revised["revision"] = 2
        revised["workpacks"][0]["workpack_id"] = "RENAMED"
        revised["workpacks"][1]["depends_on"] = ["RENAMED"]
        self.record(revised)
        self.assertEqual(self.f.advance()["status"], "BUILD_STOPPED")
        self.assertEqual(len(self.f.runner.invocations), 1)

    def test_cross_job_executor_or_artifact_change_rejected(self):
        for key, value in (("job_id", "OTHER"), ("executor", "CODEX")):
            revised = deepcopy(self.original)
            revised["workpacks"][0][key] = value
            with self.assertRaisesRegex(RequestValidationError, "binding changed"):
                adapt_build_plan(self.original, revised, self.f.scope)
        revised = deepcopy(self.original)
        revised["workpacks"][0]["artifacts"][0]["path"] = "src/other.py"
        with self.assertRaisesRegex(RequestValidationError, "binding changed"):
            adapt_build_plan(self.original, revised, self.f.scope)

    def test_merge_cannot_widen_an_individual_write_domain(self):
        self.f.scope["task_write_roots"]["IMPLEMENT-READER"] = ["src"]
        with self.assertRaisesRegex(RequestValidationError, "write scope"):
            adapt_build_plan(self.original, self.merged(), self.f.scope)

    def test_weaker_changed_or_missing_check_is_rejected(self):
        for mutation in (lambda task: task["verification"].pop(),
                         lambda task: task["verification"][0]["argv"].append("--weaker"),
                         lambda task: task["verification"][0]["artifact_ids"].append("SUMMARY")):
            revised = deepcopy(self.original)
            mutation(revised["workpacks"][0])
            with self.assertRaisesRegex(RequestValidationError, "acceptance"):
                adapt_build_plan(self.original, revised, self.f.scope)

    def test_dependency_order_and_input_scope_cannot_be_removed_or_widened(self):
        revised = deepcopy(self.original)
        revised["workpacks"][1]["depends_on"] = []
        with self.assertRaisesRegex(RequestValidationError, "dependency"):
            adapt_build_plan(self.original, revised, self.f.scope)
        revised = deepcopy(self.original)
        revised["workpacks"][0]["inputs"].append({"kind": "ARTIFACT", "id": "SUMMARY"})
        with self.assertRaisesRegex(RequestValidationError, "input scope"):
            adapt_build_plan(self.original, revised, self.f.scope)

    def test_independent_tasks_may_reorder_without_new_authority(self):
        original = deepcopy(self.original)
        original["workpacks"][1]["depends_on"] = []
        original["workpacks"][1]["inputs"] = [{"kind": "SOURCE", "id": "PROJECT-BRIEF"}]
        revised = deepcopy(original)
        revised["workpacks"].reverse()
        writes, owners = adapt_build_plan(original, revised, self.f.scope)
        self.assertEqual(writes, self.f.scope["task_write_roots"])
        self.assertEqual(owners, {key: [key] for key in writes})


if __name__ == "__main__":
    unittest.main()
