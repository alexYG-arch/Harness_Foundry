"""Domain-neutral contract alignment regressions; no model or real M1 target."""

from copy import deepcopy
import json
from unittest import TestCase
from unittest.mock import patch

from harness_foundry_factory.acceptance_contract import check_contract_examples, validate_acceptance_contracts
from harness_foundry_factory.build_authoring import read_build_task_context, record_build_plan_proposal
from harness_foundry_factory.build_entrypoint import read_build
from harness_foundry_factory.build_plan import compile_build_plan
from harness_foundry_factory.build_runtime import BuildController, classify_verification_result
from harness_foundry_factory.models import RequestValidationError
from test_build_plan import request_fixture
import test_build_runtime as support


class ContractExamplesTests(TestCase):
    def setUp(self):
        self.examples = [
            {"name": "empty", "input": [], "accepted": True},
            {"name": "nonempty-identities", "input": ["item-1", "item-2"], "accepted": True},
            {"name": "wrong-element-format", "input": [{"id": "item-1"}], "accepted": False},
        ]

    @staticmethod
    def strings(value):
        assert isinstance(value, list) and all(isinstance(row, str) for row in value)

    def test_correct_checker_matches_without_grant_or_target_acceptance(self):
        original = deepcopy(self.examples)
        result = check_contract_examples(self.strings, self.examples)
        self.assertEqual(result["status"], "CONTRACT_EXAMPLES_MATCHED")
        self.assertFalse(result["target_accepted"])
        self.assertFalse(result["semantic_completeness_verified"])
        self.assertEqual(self.examples, original)

    def test_reproduces_hidden_element_type_mismatch_and_count_only_checker(self):
        def objects(value):
            assert isinstance(value, list) and all(isinstance(row, dict) for row in value)
        for checker in (objects, lambda value: None):
            with self.subTest(checker=checker):
                result = check_contract_examples(checker, self.examples)
                self.assertEqual(result["status"], "CONTRACT_EXAMPLES_MISMATCH")
                self.assertFalse(result["examples"][-1]["matched"])
        self.assertTrue(check_contract_examples(objects, self.examples[:1])["examples"][0]["matched"],
                        "an empty array alone cannot disambiguate element types")

    def test_crash_is_not_a_successful_negative_and_examples_are_not_mutated(self):
        def broken(value):
            raise TypeError("checker defect")
        with self.assertRaisesRegex(TypeError, "checker defect"):
            check_contract_examples(broken, self.examples)
        original = deepcopy(self.examples)
        check_contract_examples(lambda value: value.clear(), self.examples)
        self.assertEqual(self.examples, original)

    def test_invalid_examples_and_all_negative_suite_are_rejected(self):
        for examples in ([], self.examples[2:], [self.examples[0]] * 2,
                         [{"name": "bad", "input": [], "accepted": "true"}]):
            with self.subTest(examples=examples), self.assertRaises(ValueError):
                check_contract_examples(self.strings, examples)

    def test_old_proposal_is_readable_but_invalid_declared_basis_is_not_ignored(self):
        request = request_fixture()
        compile_build_plan(**request)
        with self.assertRaisesRegex(RequestValidationError, "acceptance_contract"):
            validate_acceptance_contracts(request["requirement_ir"], required=True)
        for basis in ({}, {"source_id": "UNDECLARED", "source_locator": "L1"},
                      {"source_id": [], "source_locator": "L1"},
                      {"source_id": "PROJECT-BRIEF", "source_locator": 1}):
            request["requirement_ir"]["acceptance_cases"][0]["acceptance_contract"] = basis
            with self.subTest(basis=basis), self.assertRaises(RequestValidationError):
                compile_build_plan(**request)


class ContractBuildTests(TestCase):
    def setUp(self):
        self.f = support.BuildRuntimeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def test_missing_contract_stops_preparation_without_approval_or_dispatch(self):
        self.f.ir["acceptance_cases"][0].pop("acceptance_contract")
        with self.assertRaisesRegex(RequestValidationError, "acceptance_contract"):
            self.f.prepare()
        self.assertFalse(self.f.events("BUILD_AUTHORIZATION_PREPARED"))
        self.assertFalse(self.f.events("BUILD_AUTHORIZATION_APPROVED"))
        self.assertEqual(self.f.runner.invocations, [])
        history = read_build(self.f.store.database_path, self.f.program)
        self.assertEqual(history["status"], "BUILD_READBACK")

    def test_bad_locator_stops_source_capture(self):
        self.f.ir["acceptance_cases"][0]["acceptance_contract"]["source_locator"] = "L999"
        with self.assertRaises(RequestValidationError):
            self.f.prepare()
        self.assertFalse(self.f.events("BUILD_SOURCES_CAPTURED"))

    def test_resolved_contract_is_visible_in_readback_and_implementation_prompt(self):
        self.f.prepare()
        readback = read_build(self.f.store.database_path, self.f.program)
        contracts = readback["authorizations"][0]["acceptance_contracts"]
        self.assertIn("Read every row", contracts["READ-ROWS"]["text"])
        result = self.f.controller().advance(self.f.prepared_id)
        self.assertEqual(result["status"], "PLAN_CHECKS_ACCEPTED")
        prompt = self.f.runner.invocations[0]["prompt"]
        payload = json.loads(prompt.split("\n", 1)[1])
        self.assertEqual(payload["task"]["acceptance_contracts"]["READ-ROWS"], contracts["READ-ROWS"])

    def test_contract_source_reaches_task_even_if_no_atom_mentions_it(self):
        self.f.ir["sources"].append({"source_id": "PUBLIC-INTERFACE", "path_or_uri": "interface.md", "loaded_completely": True})
        self.f.ir["acceptance_cases"][0]["acceptance_contract"]["source_id"] = "PUBLIC-INTERFACE"
        event = record_build_plan_proposal(self.f.store, self.f.ir, self.f.plan,
            document_review=self.f.review, **self.f.kwargs("contract-source"))
        context = read_build_task_context(self.f.store, self.f.program, "IMPLEMENT-READER", event_id=event["event_id"])
        self.assertIn("PUBLIC-INTERFACE", [row["source_id"] for row in context["sources"]])

    def test_contract_gap_is_held_without_repair_or_successor_and_readback_explains_it(self):
        self.f.prepare()
        calls = []
        def runner(invocation, before_dispatch):
            calls.append(invocation["phase"])
            if invocation["phase"] == "IMPLEMENTATION":
                return self.f.runner(invocation, before_dispatch)
            before_dispatch()
            return classify_verification_result({"status": "VALIDATION_FAILED", "exit_code": 1,
                "stdout": json.dumps({"status": "CHECKS_FAILED", "failure_kind": "CONTRACT_GAP",
                                      "reason": "public output element format is unspecified"})})
        controller = BuildController(self.f.store, self.f.program, runner=runner, clock=support.CLOCK)
        result = controller.advance(self.f.prepared_id)
        self.assertEqual(result["status"], "HELD_ACCEPTANCE_CONTRACT")
        self.assertEqual(calls, ["IMPLEMENTATION", "VERIFICATION"])
        history = read_build(self.f.store.database_path, self.f.program)
        self.assertEqual(history["attempts"][0]["recovery"]["next_action"], "ALIGN_PUBLIC_CONTRACT_AND_VERIFIER")
        self.assertEqual(len(self.f.events("BUILD_ATTEMPT_STARTED")), 1)
        self.assertEqual(controller.advance(self.f.prepared_id)["status"], "HELD_ACCEPTANCE_CONTRACT")
        self.assertEqual(len(calls), 2)

    def test_old_scope_without_preflight_cannot_dispatch_and_history_is_unchanged(self):
        self.f.prepare()
        before = self.f.events()
        projected = deepcopy(before)
        for row in projected:
            if row["event_type"] == "BUILD_AUTHORIZATION_PREPARED":
                row["payload"].pop("acceptance_contracts")
        # Simulate an old event view; do not edit even the temporary SQLite.
        with patch.object(self.f.store, "list_events", return_value=projected):
            result = self.f.controller().advance(self.f.prepared_id)
        self.assertEqual(result["status"], "BUILD_STOPPED")
        self.assertIn("acceptance contract preflight", result["reason"])
        self.assertEqual(self.f.events(), before)
        self.assertEqual(self.f.runner.invocations, [])

    def test_observation_recovery_preserves_contract_gap_classification(self):
        from harness_foundry_factory.build_runtime import NativeBuildRunner
        self.f.prepare()
        # Exercise the same classifier on durable raw stdout as recovery uses.
        raw = {"status": "VALIDATION_FAILED", "exit_code": 1, "stdout":
               '{"status":"CHECKS_FAILED","failure_kind":"CONTRACT_GAP"}'}
        classified = classify_verification_result(raw)
        self.assertEqual(classify_verification_result(classified), classified)
        self.assertFalse(classified["automatic_retry_allowed"])
        self.assertEqual(classified["failure_domain"], "ACCEPTANCE_CONTRACT_GAP")
        with patch("harness_foundry_factory.build_runtime.CodexSandboxRunner.run", return_value=raw):
            events, prepared, plan = self.f.controller()._current(self.f.prepared_id)
            task = plan["workpacks"][0]
            invocation = self.f.controller()._invocation(prepared, task, task["verification"][0]["argv"], case_id="READ-ROWS")
            self.assertEqual(NativeBuildRunner()(invocation, lambda: None), classified)
        def runner(invocation, before_dispatch):
            if invocation["phase"] == "IMPLEMENTATION":
                return self.f.runner(invocation, before_dispatch)
            before_dispatch()
            return classified
        controller = BuildController(self.f.store, self.f.program, runner=runner, clock=support.CLOCK)
        append = controller._append
        def crash(kind, *args):
            if kind == "BUILD_ATTEMPT_FINISHED":
                raise support.InjectedControllerCrash()
            return append(kind, *args)
        with patch.object(controller, "_append", side_effect=crash), self.assertRaises(support.InjectedControllerCrash):
            controller.advance(self.f.prepared_id)
        self.assertFalse(self.f.events("BUILD_ATTEMPT_FINISHED"))
        result = self.f.controller().advance(self.f.prepared_id)
        self.assertEqual(result["status"], "HELD_ACCEPTANCE_CONTRACT")
        self.assertEqual(len(self.f.runner.invocations), 1, "recovery must not run implementation or later checks again")
        self.assertEqual(len(self.f.events("BUILD_COMMAND_PLANNED")), 2)
        self.assertTrue(self.f.events("BUILD_ATTEMPT_FINISHED")[0]["payload"]["recovered_from_observation"])
