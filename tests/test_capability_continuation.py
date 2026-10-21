"""Selected capability materials enter the existing continuation controller.

Every Program, approval, package and target here is disposable test data. Local
processes and durable reports are real; this does not qualify a native sandbox,
real target Harness, model, external service or second device.
"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

from harness_foundry_factory.build_authoring import record_build_plan_proposal
from harness_foundry_factory.build_entrypoint import read_build
from harness_foundry_factory.build_runtime import (
    approve_build_authorization, prepare_build_authorization, record_source_snapshot,
)
from harness_foundry_factory.build_state import (
    attempt_budget, project_budget_attempts, project_execution_state,
)
import test_build_runtime as support
from test_build_resources import DurableResourceFixtureRunner
from tests.build_review_fixture import reviewed_document


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'continuation_capability_consume', ROOT / 'examples/capability-adapters/consume.py')
CONSUME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONSUME)
PREPARE = CONSUME._prepare

CHECKER = support.VERIFIER + '''
import os
if "FOUNDRY_REPORT_DIR" in os.environ:
    report = {"schema_version": "1.0", "case_id": os.environ["FOUNDRY_CASE_ID"],
              "command_id": os.environ["FOUNDRY_COMMAND_ID"], "status": "CHECKS_PASS",
              "checks": [{"id": "reader", "status": "PASS"}], "errors": []}
    Path(os.environ["FOUNDRY_REPORT_DIR"], "summary.json").write_text(json.dumps(report))
'''


def files_below(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob('*') if path.is_file()}


class CapabilityContinuationTests(unittest.TestCase):
    def setUp(self):
        self.f = support.BuildRuntimeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.scope['max_attempts'] = 12
        self.base_request = deepcopy(self.f.request)
        self.base_scope = deepcopy(self.f.scope)
        self.packages = self.f.root / 'packages'
        self.packages.mkdir()
        self.resource_root = self.f.root / 'resource-runs'
        self.resource_root.mkdir()
        self.sequence = 0
        self.package_versions = {}
        for version in ('1', '2'):
            package = self.packages / ('reader-' + version)
            package.mkdir()
            (package / 'guide.md').write_text('Build the project reader using the explicit selected tool.\n')
            product = support.GOOD_READER + '\nCAPABILITY_VERSION = ' + repr(version) + '\n'
            (package / 'build_reader.py').write_text(
                'from pathlib import Path\nPath("src/reader.py").write_text(' + repr(product) + ')\n')
            (package / 'check.py').write_text(CHECKER)
            descriptor = {
                'name': 'reader', 'version': version, 'usage': 'both',
                'inputs': ['Project reader contract'], 'outputs': ['Reader and downstream report'],
                'materials': ['guide.md'], 'tools': [{'id': 'build-reader',
                    'path': 'build_reader.py', 'interpreter': 'python', 'interpreter_args': ['-I', '-B']}],
                'verification_files': ['check.py'],
                'environment': [{'id': 'python', 'kind': 'executable'},
                                {'id': 'report-python', 'kind': 'executable'}],
            }
            (package / 'capability.json').write_text(json.dumps(descriptor))
            self.package_versions[version] = package
        self.original_packages = files_below(self.packages)

    def materials(self, version='1', *, report_python=None, resource=False):
        self.sequence += 1
        key = 'materials-' + str(self.sequence)
        verifier = self.f.root / (key + '-verifier')
        verifier.mkdir()
        scope = deepcopy(self.base_scope)
        scope['verification_root'] = str(verifier)
        request = deepcopy(self.base_request)
        request['plan']['schema_version'] = '1.2'
        request['plan']['revision'] = self.sequence
        if resource:
            scope['verification_resources'] = {
                'schema_version': '1.0', 'root': str(self.resource_root), 'profiles': {
                    'reader': {'writable_areas': ['scratch', 'report-staging'],
                               'network': {'mode': 'NONE'}, 'services': [],
                               'result_protocol': 'STRUCTURED_V1',
                               'report_files': ['summary.json'], 'required_checks': ['reader'],
                               'retention': {'success': 'REPORTS_ONLY', 'failure_days': 7}}}}
        for task in request['plan']['workpacks']:
            for check in task['verification']:
                check['argv'][3] = 'verifier://capabilities/reader/check.py'
                if task['workpack_id'] == 'MAKE-REPORT':
                    check['argv'][0] = 'report-python'
                if resource:
                    check['resource_profile_ref'] = 'reader'
        config = {
            'project_root': str(self.f.root), 'source_root': str(self.f.source),
            'base_materials': {'request': request, 'scope': scope,
                              'source_manifest': [{'source_id': 'PROJECT-BRIEF', 'path': 'brief.md'}]},
            'selections': [{'directory': str(self.package_versions[version]), 'version': version,
                            'workpack_ids': ['IMPLEMENT-READER']}],
            'environment_bindings': {'python': {'path': sys.executable},
                'report-python': {'path': str(report_python or sys.executable)}},
        }
        materials = PREPARE.write_materials(config, self.f.root / key)
        self.assertEqual(materials['preparation']['readiness'], 'READY')
        for item in materials['preparation']['verifier_inputs']:
            destination = verifier / item['path']
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(Path(item['source']).read_bytes())
        call = CONSUME.prepare_call(materials, 'build-reader')
        self.assertFalse(call['commands_executed'])
        materials['request']['plan']['workpacks'][0]['local_argv'] = call['local_argv']
        self.assertIn({'kind': 'SOURCE', 'id': 'CAP-reader-VERSION'},
                      materials['request']['plan']['workpacks'][0]['inputs'])
        return materials

    def authorize(self, materials, *, previous=None):
        f = self.f
        prefix = 'binding-' + str(self.sequence)
        request = materials['request']
        source_root = Path(materials['preparation']['source_root'])
        review = reviewed_document(source_root, path=source_root / 'brief.md')
        review['version'] = prefix
        review['presentation']['turn_id'] = prefix + '-synthetic-presentation'
        review['decision']['actor']['turn_id'] = prefix + '-synthetic-confirmation'
        proposal = record_build_plan_proposal(f.store, request['requirement_ir'], request['plan'],
                                             document_review=review, **f.kwargs(prefix + '-proposal'))
        source = record_source_snapshot(f.store, f.program, proposal['event_id'], source_root,
                                        materials['source_manifest'], **f.kwargs(prefix + '-sources'))
        prepared = prepare_build_authorization(f.store, f.program, proposal['event_id'], source['event_id'],
            materials['scope'], rebind_from=previous, **f.kwargs(prefix + '-prepare'))
        approval = approve_build_authorization(f.store, f.program, prepared['event_id'],
            human_message_ref='SYNTHETIC TEST ONLY: selected-capability continuation',
            **f.kwargs(prefix + '-approve'))
        return prepared['event_id'], approval['payload'].get('rebind', {})

    def usage(self, prepared):
        return attempt_budget(self.base_scope,
            list(project_budget_attempts(self.f.events(), prepared).values()))

    def accepted(self, prepared):
        result = self.f.controller().advance(prepared)
        self.assertEqual(result['status'], 'PLAN_CHECKS_ACCEPTED', result)

    def corrected_report_binding(self, *, resource=False):
        first_materials = self.materials(resource=resource)
        first, _ = self.authorize(first_materials)
        self.accepted(first)
        invocation = self.f.root / 'corrected-check-environment' / 'python'
        invocation.parent.mkdir()
        invocation.symlink_to(sys.executable)
        corrected = self.materials(report_python=invocation, resource=resource)
        # Only the actual checker invocation changes. The production capability
        # and public selected-version source keep the same bytes and meanings.
        relative = 'capabilities/reader/selected-version.json'
        self.assertEqual((Path(first_materials['preparation']['source_root']) / relative).read_bytes(),
                         (Path(corrected['preparation']['source_root']) / relative).read_bytes())
        second, continuation = self.authorize(corrected, previous=first)
        self.assertEqual(set(continuation['accepted']), {'IMPLEMENT-READER'})
        self.assertEqual(set(continuation['verification_pending']), {'MAKE-REPORT'})
        self.assertEqual(continuation['rebuild_workpack_ids'], [])
        self.assertFalse(continuation['budget_reset'])
        return first, second

    def test_selected_version_source_drives_existing_rebuild_and_preserves_budget(self):
        f = self.f
        old_materials = self.materials('1')
        first, _ = self.authorize(old_materials)
        self.accepted(first)
        old_events = deepcopy(f.events())
        old_product = (f.workspace / 'src/reader.py').read_bytes()
        new_materials = self.materials('2')
        second, continuation = self.authorize(new_materials, previous=first)
        self.assertEqual(continuation['rebuild_workpack_ids'], ['IMPLEMENT-READER'])
        self.assertEqual(continuation['accepted'], {})
        self.assertEqual(self.usage(second)['attempts_consumed'], 2)
        self.assertEqual(self.usage(second)['attempts_remaining'], 10)
        self.assertEqual((f.workspace / 'src/reader.py').read_bytes(), old_product)
        self.assertEqual(CONSUME.prepare_call(old_materials, 'build-reader')['version'], '1')
        before = len(f.runner.invocations)
        self.accepted(second)
        calls = f.runner.invocations[before:]
        self.assertEqual([row['workpack_id'] for row in calls if row['phase'] == 'IMPLEMENTATION'],
                         ['IMPLEMENT-READER', 'MAKE-REPORT'])
        self.assertIn(b"CAPABILITY_VERSION = '2'", (f.workspace / 'src/reader.py').read_bytes())
        self.assertEqual(self.usage(second)['attempts_consumed'], 4)
        self.assertEqual(self.usage(second)['task_attempts_consumed'],
                         {'IMPLEMENT-READER': 2, 'MAKE-REPORT': 2})
        self.assertEqual(f.events()[:len(old_events)], old_events)
        self.assertEqual(files_below(self.packages), self.original_packages)

    def test_selected_checker_environment_rebind_only_reverifies_affected_task(self):
        f = self.f
        first, second = self.corrected_report_binding()
        product = files_below(f.workspace)
        before = len(f.runner.invocations)
        result = f.controller().advance(second, advance_mode='ONE_ATTEMPT')
        self.assertEqual(result['attempt_status'], 'ACCEPTED', result)
        self.assertEqual([(row['phase'], row['case_id']) for row in f.runner.invocations[before:]],
                         [('VERIFICATION', 'REPORT-COUNT')])
        self.assertEqual(self.usage(second)['attempts_consumed'], 3)
        self.assertEqual(self.usage(second)['task_attempts_consumed'],
                         {'IMPLEMENT-READER': 1, 'MAKE-REPORT': 2})
        attempts, accepted = project_execution_state(f.events(), second)
        self.assertEqual(len(attempts), 1)
        self.assertTrue(next(iter(attempts.values()))['reverification_of_attempt_id'])
        self.assertEqual(accepted['IMPLEMENT-READER']['prepared_event_id'], first)
        count = len(f.events())
        for _ in range(2):
            view = read_build(f.store.database_path, f.program)
            self.assertEqual(view['authorizations'][-1]['budget']['attempts_consumed'], 3)
        self.accepted(second)
        self.assertEqual(len(f.events()), count)
        self.assertEqual(len(f.runner.invocations), before + 1)
        self.assertEqual(files_below(f.workspace), product)

    def test_capability_reverification_capture_recovers_without_replay_or_recount(self):
        f = self.f
        f.runner = DurableResourceFixtureRunner()
        _, second = self.corrected_report_binding(resource=True)
        before = len(f.runner.invocations)
        product = files_below(f.workspace)

        def interrupt(invocation, result):
            f.runner.after_run = None
            raise support.InjectedControllerCrash()

        f.runner.after_run = interrupt
        with self.assertRaises(support.InjectedControllerCrash):
            f.controller().advance(second, advance_mode='ONE_ATTEMPT')
        self.assertEqual(len(f.runner.invocations), before + 1)
        attempt = next(iter(project_execution_state(f.events(), second)[0]))
        self.assertEqual(self.usage(second)['attempts_consumed'], 3)
        result = f.controller().advance(second, advance_mode='ONE_ATTEMPT')
        self.assertEqual((result['attempt_status'], result['attempt_id']), ('ACCEPTED', attempt), result)
        observed = [row['payload'] for row in f.events('BUILD_COMMAND_OBSERVED')
                    if row['payload']['attempt_id'] == attempt]
        self.assertEqual(len(observed), 1)
        command = observed[0]
        self.assertEqual(command['result']['resource_cleanup']['status'], 'CLEANED')
        self.assertTrue(all(not Path(path).exists() for path in command['resource_binding']['areas'].values()))
        report = Path(command['observation_root']) / 'reports/summary.json'
        retained = report.read_bytes()
        self.assertEqual(json.loads(retained)['command_id'], command['command_id'])
        event_count = len(f.events())
        for _ in range(2):
            self.accepted(second)
            self.assertEqual(report.read_bytes(), retained)
        self.assertEqual(len(f.events()), event_count)
        self.assertEqual(len(f.runner.invocations), before + 1)
        self.assertEqual(self.usage(second)['attempts_consumed'], 3)
        self.assertEqual(files_below(f.workspace), product)
        self.assertEqual(files_below(self.packages), self.original_packages)


if __name__ == '__main__':
    unittest.main()
