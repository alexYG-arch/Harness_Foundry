"""One-confirmation workflow: synthetic host decisions, no real model grants."""

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from harness_foundry_factory import build_preview as preview_api
from harness_foundry_factory.build_preview import preview_build, materialize_build_preview
from harness_foundry_factory.build_runtime import BuildController, revoke_build_authorization
from harness_foundry_factory.build_types import RequestValidationError, IdempotencyConflictError
from harness_foundry_factory.revision_store import RevisionControlEventStore
import test_build_runtime as support


class BuildPreviewTests(unittest.TestCase):
    def setUp(self):
        self.f = support.BuildRuntimeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.db = self.f.root / "one-confirmation.sqlite3"
        self.path = self.f.root / "host-preparation" / "preview-v1.json"
        self.request = {"preview_path": str(self.path),
            "document": {k: deepcopy(v) for k, v in self.f.review.items() if k not in {"presentation", "decision"}},
            "requirement_ir": self.f.ir, "plan": self.f.plan, "source_root": str(self.f.source),
            "manifest": [{"source_id": "PROJECT-BRIEF", "path": "brief.md"}], "scope": self.f.scope}
        self.clock = lambda: support.NOW

    def preview(self):
        return preview_build(self.request, str(self.db), clock=self.clock)

    def confirm(self, preview=None):
        preview = preview or self.preview()
        decision = deepcopy(self.f.review["decision"])
        decision["action"] = "CONFIRM_BUILD_AND_RUNTIME"
        decision["user_message"] = "TEST ONLY: confirm the complete displayed build and runtime scope"
        return {"preview_path": str(self.path), "preview_sha256": preview["preview_sha256"],
                "presentation": deepcopy(self.f.review["presentation"]), "decision": decision,
                "expected_revision": 0, "idempotency_key": "one-confirmation"}

    def materialize(self, request=None):
        return materialize_build_preview(request or self.confirm(), str(self.db), clock=self.clock)

    def events(self):
        return RevisionControlEventStore(self.db, read_only=True).list_events(self.f.program)

    def test_preview_creates_no_program_target_or_execution(self):
        (self.f.workspace / 'src').rmdir()
        (self.f.workspace / 'outputs').rmdir()
        self.f.workspace.rmdir()
        with patch('subprocess.Popen', side_effect=AssertionError('no execution')):
            result = self.preview()
        self.assertFalse(self.db.exists())
        self.assertFalse(self.f.workspace.exists())
        self.assertFalse(result['readback']['runtime_authorized'])
        self.assertEqual(result['readback']['prepared']['scope']['max_attempts'], 5)
        self.assertIn(self.f.source_text, json.dumps(result, ensure_ascii=False).replace('\\n', '\n'))
        self.assertEqual(self.preview(), result)

    def test_one_real_combined_decision_materializes_once_and_runs_existing_controller(self):
        request = self.confirm()
        with patch('subprocess.Popen', side_effect=AssertionError('preparation must not execute')):
            result = self.materialize(request)
            repeated = self.materialize(request)
        self.assertEqual(result, repeated)
        events = self.events()
        self.assertEqual([e['event_type'] for e in events], ['BUILD_PREVIEW_CONFIRMED', 'BUILD_PLAN_PROPOSED',
            'BUILD_SOURCES_CAPTURED', 'BUILD_AUTHORIZATION_PREPARED', 'BUILD_AUTHORIZATION_APPROVED'])
        self.assertEqual(events[0]['payload']['request']['decision'], request['decision'])
        self.assertEqual(events[-1]['payload']['approval_basis']['confirmation_event_id'], events[0]['event_id'])
        controller = BuildController(RevisionControlEventStore(self.db), self.f.program,
            runner=self.f.runner, clock=support.CLOCK)
        self.assertEqual(controller.advance(result['prepared_event_id'])['status'], 'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(controller.advance(result['prepared_event_id'])['status'], 'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(len(self.f.runner.invocations), 5)
        self.assertEqual(len([e for e in self.events() if e['event_type'] == 'BUILD_ATTEMPT_STARTED']), 2)

    def test_contract_only_prepare_only_or_agent_decision_cannot_materialize(self):
        request = self.confirm()
        for action, actor in [('CONFIRM_BUILD_DOCUMENT', 'HUMAN_VIA_CODEX_CHAT'),
                              ('CONTINUE_PREPARATION', 'HUMAN_VIA_CODEX_CHAT'),
                              ('CONFIRM_BUILD_AND_RUNTIME', 'AGENT')]:
            bad = deepcopy(request)
            bad['decision']['action'] = action
            bad['decision']['actor']['type'] = actor
            with self.subTest(action=action), self.assertRaises(RequestValidationError):
                self.materialize(bad)
            self.assertFalse(self.db.exists())

    def test_same_presentation_turn_or_other_thread_is_not_later_human_confirmation(self):
        request = self.confirm()
        for changes in ({'turn_id': request['presentation']['turn_id']}, {'chat_thread_id': 'OTHER'}):
            bad = deepcopy(request)
            bad['decision']['actor'].update(changes)
            with self.assertRaises(RequestValidationError):
                self.materialize(bad)
        self.assertFalse(self.db.exists())

    def test_source_and_checker_drift_rejected_before_program_creation(self):
        request = self.confirm()
        for path in (self.f.source / 'brief.md', self.f.verifier / 'check.py'):
            old = path.read_bytes()
            path.write_bytes(old + b'\n# changed\n')
            with self.subTest(path=path), self.assertRaises(RequestValidationError):
                self.materialize(request)
            self.assertFalse(self.db.exists())
            path.write_bytes(old)
        self.assertEqual(self.materialize(request)['status'], 'BUILD_PREVIEW_MATERIALIZED')

    def test_preview_body_and_scope_substitution_cannot_reuse_shown_digest(self):
        request = self.confirm()
        old = self.path.read_bytes()
        body = json.loads(old)
        body['prepared']['scope']['max_attempts'] += 1
        self.path.write_text(json.dumps(body))
        with self.assertRaisesRegex(RequestValidationError, 'identity/content'):
            self.materialize(request)
        body['sha256'] = preview_api._digest({k:v for k,v in body.items() if k != 'sha256'})
        self.path.write_text(json.dumps(body))
        with self.assertRaisesRegex(RequestValidationError, 'different preview'):
            self.materialize(request)
        self.assertFalse(self.db.exists())
        self.path.write_bytes(old)

    def test_expiry_is_absolute_and_not_extended_by_materialization(self):
        request = self.confirm()
        with self.assertRaisesRegex(RequestValidationError, 'expired'):
            materialize_build_preview(request, str(self.db), clock=lambda: self.f.scope['expires_at'])
        self.assertFalse(self.db.exists())

    def test_each_partial_stage_resumes_without_duplicate_records(self):
        for index, function in enumerate(('record_build_plan_proposal', 'record_source_snapshot', 'prepare_build_authorization')):
            with self.subTest(function=function):
                self.db = self.f.root / f'interrupted-{index}.sqlite3'
                self.path = self.f.root / 'host-preparation' / f'interrupted-{index}.json'
                self.request['preview_path'] = str(self.path)
                request = self.confirm()
                with patch.object(preview_api, function, side_effect=support.InjectedControllerCrash):
                    with self.assertRaises(support.InjectedControllerCrash):
                        self.materialize(request)
                self.assertFalse(any(e['event_type'] == 'BUILD_AUTHORIZATION_APPROVED' for e in self.events()))
                result = self.materialize(request)
                self.assertEqual(len(self.events()), 5)
                self.assertEqual(self.materialize(request), result)

    def test_complete_materialization_retrieval_survives_expiry_and_missing_preparation(self):
        request = self.confirm()
        result = self.materialize(request)
        self.path.unlink()
        (self.f.source / 'brief.md').unlink()
        (self.f.verifier / 'check.py').unlink()
        with patch('subprocess.Popen', side_effect=AssertionError('no replay')):
            retrieved = materialize_build_preview(request, str(self.db), clock=lambda: self.f.scope['expires_at'])
        self.assertEqual(retrieved, result)
        self.assertEqual(len(self.events()), 5)
        self.assertFalse(retrieved['authority_revalidated'])

    def test_revocation_remains_effective_after_complete_preview_retrieval(self):
        request = self.confirm()
        result = self.materialize(request)
        store = RevisionControlEventStore(self.db)
        revoke_build_authorization(store, self.f.program, result['prepared_event_id'], expected_revision=5,
            idempotency_key='revoke', created_at=support.NOW, human_message_ref='TEST human revocation')
        self.assertEqual(self.materialize(request)['event_id'], result['event_id'])
        controller = BuildController(store, self.f.program, runner=self.f.runner, clock=support.CLOCK)
        self.assertEqual(controller.advance(result['prepared_event_id'])['status'], 'BUILD_STOPPED')
        self.assertFalse(self.f.runner.invocations)

    def test_revocation_during_partial_materialization_cannot_be_overridden(self):
        request = self.confirm()
        original = preview_api.prepare_build_authorization
        def interrupted(*args, **kwargs):
            result = original(*args, **kwargs)
            store = args[0]
            revoke_build_authorization(store, self.f.program, result['event_id'], expected_revision=result['stream_revision'],
                idempotency_key='revoke-before-final', created_at=support.NOW, human_message_ref='TEST human stop')
            raise support.InjectedControllerCrash()
        with patch.object(preview_api, 'prepare_build_authorization', side_effect=interrupted):
            with self.assertRaises(support.InjectedControllerCrash):
                self.materialize(request)
        with self.assertRaisesRegex(RequestValidationError, 'stream changed'):
            self.materialize(request)
        self.assertFalse(any(e['event_type'] == 'BUILD_AUTHORIZATION_APPROVED' for e in self.events()))

    def test_reused_key_with_other_human_decision_is_conflict_not_new_authority(self):
        request = self.confirm()
        self.materialize(request)
        changed = deepcopy(request)
        changed['decision']['actor']['turn_id'] = 'DIFFERENT-TURN'
        with self.assertRaises(IdempotencyConflictError):
            self.materialize(changed)
        self.assertEqual(len(self.events()), 5)

    def resource_preview(self):
        self.f.plan['schema_version'] = '1.2'
        self.f.plan['workpacks'][0]['verification'][0]['resource_profile_ref'] = 'dev'
        self.f.scope['verification_resources'] = {'schema_version': '1.0', 'root': str(self.f.root / 'resources'),
            'checker_files': ['helper.py'], 'profiles': {'dev': {'writable_areas': ['scratch', 'report-staging'],
            'network': {'mode': 'NONE'}, 'services': [], 'result_protocol': 'STRUCTURED_V1',
            'required_checks': ['read'], 'report_files': ['summary.json'],
            'retention': {'success': 'REPORTS_ONLY', 'failure_days': 7}}}}
        (self.f.verifier / 'helper.py').write_text('EXPECTED = 3\n')
        return self.confirm()

    def test_resource_snapshot_is_fixed_in_preview_and_reused_after_confirmation(self):
        request = self.resource_preview()
        preview = json.loads(self.path.read_text())
        root = Path(preview['prepared']['verifier_source']['runtime_root'])
        self.assertTrue((root / 'helper.py').is_file())
        self.assertFalse(self.db.exists())
        before = sorted(root.parent.iterdir())
        result = self.materialize(request)
        self.assertEqual(sorted(root.parent.iterdir()), before)
        prepared = next(e for e in self.events() if e['event_id'] == result['prepared_event_id'])
        self.assertEqual(prepared['payload']['scope']['verification_root'], str(root))

    def test_resource_source_and_protected_snapshot_drift_both_rejected(self):
        request = self.resource_preview()
        preview = json.loads(self.path.read_text())
        root = Path(preview['prepared']['verifier_source']['runtime_root'])
        for path in (self.f.verifier / 'helper.py', root / 'helper.py'):
            old = path.read_bytes()
            path.chmod(0o644)
            path.write_bytes(b'EXPECTED = 999\n')
            with self.subTest(path=path), self.assertRaises(RequestValidationError):
                self.materialize(request)
            path.write_bytes(old)
        self.assertFalse(self.db.exists())

    def test_preview_cannot_overwrite_existing_program_or_workspace(self):
        self.f.prepare()
        with self.assertRaisesRegex(RequestValidationError, 'existing Program'):
            preview_build(self.request, str(self.f.store.database_path), clock=self.clock)
        self.request['preview_path'] = str(self.f.workspace / 'preview.json')
        with self.assertRaisesRegex(RequestValidationError, 'host-owned'):
            self.preview()
        self.assertFalse(self.db.exists())

    def test_model_context_after_one_confirmation_has_actual_binding(self):
        self.f.plan['workpacks'][0]['executor'] = 'CODEX'
        self.f.plan['workpacks'][0].pop('local_argv')
        self.f.scope.update(model='test-model', model_reasoning_effort='high', allow_model_service=True)
        result = self.materialize()
        controller = BuildController(RevisionControlEventStore(self.db), self.f.program,
            runner=self.f.runner, clock=support.CLOCK)
        _, prepared, plan = controller._current(result['prepared_event_id'])
        invocation = controller._invocation(prepared, plan['workpacks'][0], [])
        task = json.loads(invocation['prompt'].split('\n', 1)[1])['task']
        self.assertTrue(task['authority_validated'])
        self.assertEqual(task['runtime_authorization']['prepared_event_id'], result['prepared_event_id'])
        self.assertEqual(task['runtime_authorization']['approval_event_id'], result['event_id'])
        self.assertFalse(task['execution_started'])
        self.assertFalse(self.f.runner.invocations)

    def test_following_defaults_and_freezing_defaults_keep_distinct_policy(self):
        self.f.plan['workpacks'][0]['executor'] = 'CODEX'
        self.f.plan['workpacks'][0].pop('local_argv')
        self.f.scope['allow_model_service'] = True
        chosen = {'model': 'test-model', 'model_reasoning_effort': 'high',
                  'model_service': {'provider': 'openai', 'config': {}},
                  'model_defaults_source': {'kind': 'TEST_ONLY_DEFAULTS'}}
        with patch('harness_foundry_factory.coding_defaults.resolve_codex_defaults', return_value=chosen):
            result = self.preview()
            self.assertEqual(result['readback']['prepared']['scope']['model_policy'], 'CODEX_GLOBAL_DEFAULTS')
            self.assertIsNone(result['readback']['prepared']['scope']['model'])
            self.materialize(self.confirm(result))
        self.db = self.f.root / 'frozen.sqlite3'
        self.path = self.f.root / 'host-preparation' / 'frozen.json'
        self.request['preview_path'] = str(self.path)
        self.request['follow_codex_defaults'] = True
        with patch('harness_foundry_factory.coding_defaults.resolve_codex_defaults', return_value=chosen):
            frozen = self.preview()
        self.assertEqual(frozen['readback']['prepared']['scope']['model'], 'test-model')
        with patch('harness_foundry_factory.coding_defaults.resolve_codex_defaults', side_effect=AssertionError('frozen')):
            self.materialize(self.confirm(frozen))

    def test_public_entrypoints_retain_complete_readback_without_model_dispatch(self):
        from harness_foundry_factory.build_entrypoint import apply_build_request, read_build
        with patch.object(preview_api, '_now', return_value=support.NOW), \
                patch('subprocess.Popen', side_effect=AssertionError('no dispatch')):
            preview = apply_build_request('preview-build', self.request, str(self.db))
            self.assertFalse(self.db.exists())
            result = apply_build_request('materialize-build-preview', self.confirm(preview), str(self.db))
            view = read_build(str(self.db), self.f.program)
        self.assertEqual(view['authorizations'][0]['prepared_event_id'], result['prepared_event_id'])
        self.assertEqual(view['authorizations'][0]['state'], 'EXPIRED', 'readback uses actual current clock')
        self.assertEqual(view['document_review']['decision']['action'], 'CONFIRM_BUILD_AND_RUNTIME')
        # Private preparation stays host-owned. Runtime task context contains
        # public documents, never the complete preview/private checker files.
        self.assertFalse(view['attempts'])

    def test_committed_steps_survive_lost_response_without_repeating_step(self):
        for index, function in enumerate(('record_build_plan_proposal', 'record_source_snapshot', 'prepare_build_authorization')):
            with self.subTest(function=function):
                self.db = self.f.root / f'lost-response-{index}.sqlite3'
                self.path = self.f.root / 'host-preparation' / f'lost-response-{index}.json'
                self.request['preview_path'] = str(self.path)
                request = self.confirm()
                original = getattr(preview_api, function)
                def lost_response(*args, **kwargs):
                    original(*args, **kwargs)
                    raise support.InjectedControllerCrash()
                with patch.object(preview_api, function, side_effect=lost_response):
                    with self.assertRaises(support.InjectedControllerCrash):
                        self.materialize(request)
                before = self.events()
                result = self.materialize(request)
                self.assertEqual(self.events()[:len(before)], before)
                self.assertEqual(len(self.events()), 5)
                self.assertEqual(result['prepared_event_id'], self.events()[3]['event_id'])

    def test_concurrent_materialization_uses_cas_and_converges_to_same_records(self):
        from concurrent.futures import ThreadPoolExecutor
        from harness_foundry_factory.build_types import FactoryError
        request = self.confirm()
        # Creating an empty native controller is test fixture setup. Neither
        # worker has a Program or runtime grant at the start.
        RevisionControlEventStore(self.db)
        def run():
            try:
                return self.materialize(request)
            except FactoryError:
                # A losing CAS is a safe interruption, not a second approval.
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        final = self.materialize(request)
        self.assertEqual(len(self.events()), 5)
        for result in results:
            if result is not None:
                self.assertEqual(result['prepared_event_id'], final['prepared_event_id'])
        self.assertFalse(self.f.runner.invocations)

    def test_preview_authority_supports_same_scope_reverification_and_root_revocation(self):
        from test_build_correction import CheckerCorrectionTests
        from test_build_resources import DurableResourceFixtureRunner
        from harness_foundry_factory.build_runtime import classify_verification_result
        from harness_foundry_factory.build_state import attempt_budget, project_budget_attempts
        (self.f.verifier / 'check.py').write_text("raise PermissionError('TEST omitted adapter setup')\n")
        result = self.materialize()
        events = self.events()
        self.f.store = RevisionControlEventStore(self.db)
        self.f.prepared_id = result['prepared_event_id']
        self.f.proposal_id = events[1]['event_id']
        self.f.source_id = events[2]['event_id']
        runner = DurableResourceFixtureRunner()
        def run(invocation, before):
            answer = runner(invocation, before)
            return classify_verification_result(answer) if invocation['phase'] == 'VERIFICATION' else answer
        self.f.runner = run
        first = self.f.controller().advance(self.f.prepared_id, advance_mode='ONE_ATTEMPT')
        self.assertEqual(first['attempt_status'], 'BLOCKED')
        helper = CheckerCorrectionTests()
        helper.f = self.f
        new, evidence = helper.new_binding(complete=first['attempt_id'])
        helper.derive(new, evidence)
        before = len(runner.invocations)
        fixed = self.f.controller().advance(new, advance_mode='ONE_ATTEMPT')
        self.assertEqual(fixed['attempt_status'], 'ACCEPTED', fixed)
        self.assertTrue(all(row['phase'] == 'VERIFICATION' for row in runner.invocations[before:]))
        budget = attempt_budget(self.f.scope, list(project_budget_attempts(self.events(), new).values()))
        self.assertEqual(budget['attempts_consumed'], 1)
        revoke_build_authorization(self.f.store, self.f.program, self.f.prepared_id, **self.f.kwargs('root-revoke'))
        before = len(runner.invocations)
        self.assertEqual(self.f.controller().advance(new)['status'], 'BUILD_STOPPED')
        self.assertEqual(len(runner.invocations), before)
        self.assertEqual(len([e for e in self.events() if e['event_type'] == 'BUILD_PREVIEW_CONFIRMED']), 1)

    def test_confirmation_only_interruption_is_readable_without_materializing(self):
        from harness_foundry_factory.build_entrypoint import read_build
        request = self.confirm()
        with patch.object(preview_api, 'record_build_plan_proposal', side_effect=support.InjectedControllerCrash):
            with self.assertRaises(support.InjectedControllerCrash):
                self.materialize(request)
        captured = self.events()
        self.path.unlink()
        before = self.db.read_bytes()
        with patch('subprocess.Popen', side_effect=AssertionError('read only')):
            view = read_build(str(self.db), self.f.program)
            repeated = read_build(str(self.db), self.f.program)
        self.assertEqual(view, repeated)
        self.assertEqual(view['status'], 'BUILD_PREVIEW_MATERIALIZATION_PENDING')
        self.assertEqual(view['confirmed_previews'][0]['preview'], captured[0]['payload']['preview'])
        self.assertIsNone(view['proposal'])
        self.assertEqual(view['authorizations'], [])
        self.assertEqual(view['attempts'], [])
        self.assertNotIn('budget', view)
        self.assertFalse(view['runtime_authorized'])
        self.assertFalse(view['writes_performed'])
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(self.materialize(request)['status'], 'BUILD_PREVIEW_MATERIALIZED')
        self.assertEqual(self.events()[:1], captured)

    def test_empty_controller_keeps_original_missing_proposal_error(self):
        from harness_foundry_factory.build_entrypoint import read_build
        RevisionControlEventStore(self.db)
        before = self.db.read_bytes()
        with self.assertRaisesRegex(RequestValidationError, 'build proposal does not exist'):
            read_build(str(self.db), self.f.program)
        self.assertEqual(self.db.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
