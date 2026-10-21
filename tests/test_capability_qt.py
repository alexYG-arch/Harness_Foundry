"""Qt adapter contracts with test-owned commands, not native/target acceptance."""

import importlib.util
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


PACKAGE = Path(__file__).resolve().parents[1] / 'examples/capability-adapters/packages/qt-cmake/1'


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, PACKAGE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TOOL = load('capability_qt_tool', 'qt_cmake.py')
CHECK = load('capability_qt_check', 'check_ctest.py')


class CapabilityQtTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='capability-qt-test-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / 'source'
        self.source.mkdir()
        (self.source / 'CMakeLists.txt').write_text('# test-owned source\n')
        self.build = self.root / 'build'
        self.build.mkdir()
        self.report = self.root / 'report'
        self.expected = self.root / 'expected.json'
        self.expected.write_text(json.dumps({'required_tests': ['project-alpha']}))

    def args(self, command, *extra):
        flag = '--ctest' if command == 'test' else '--cmake'
        args = [command, flag, sys.executable, '--build-dir', str(self.build),
                '--report-dir', str(self.report), *extra]
        if command == 'configure':
            args.extend(['--source', str(self.source)])
        return TOOL.parser().parse_args(args)

    def checker_args(self, **changes):
        return SimpleNamespace(**{'ctest': sys.executable, 'build_dir': str(self.build),
            'report_dir': str(self.report), 'expected': str(self.expected), 'config': None,
            'test_regex': None, **changes})

    def inspect(self, xml, code=0, status='FINISHED', required=None):
        path = self.root / 'junit.xml'
        path.write_text(xml)
        return CHECK.inspect_report(path, {'status': status, 'returncode': code},
                                    required or ['project-alpha'])

    def test_manifest_keeps_checker_out_of_producer_materials(self):
        descriptor = json.loads((PACKAGE / 'capability.json').read_text())
        self.assertEqual((descriptor['name'], descriptor['version'], descriptor['usage']), ('qt-cmake', '1', 'both'))
        self.assertEqual(descriptor['verification_files'], ['check_ctest.py'])
        public = [*descriptor['materials'], *(entry['path'] for entry in descriptor['tools'])]
        self.assertNotIn('check_ctest.py', public)
        self.assertFalse(any('expected' in name for name in public))
        for name in [*public, *descriptor['verification_files']]:
            self.assertTrue((PACKAGE / name).is_file())

    def test_configure_passes_project_arguments_without_install_or_shell(self):
        before = (self.source / 'CMakeLists.txt').read_bytes()
        with patch.object(TOOL.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            record = TOOL.run(self.args('configure', '--generator', 'Ninja', '--config', 'Debug',
                '--define', 'CMAKE_PREFIX_PATH=/selected sdk', '--define', 'PROJECT_SWITCH:BOOL=ON'))
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], [sys.executable, '-S', str(self.source), '-B', str(self.build),
            '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Debug', '-DCMAKE_PREFIX_PATH=/selected sdk', '-DPROJECT_SWITCH:BOOL=ON'])
        self.assertNotIn('shell', run.call_args.kwargs)
        self.assertEqual(record['status'], 'FINISHED')
        self.assertEqual((self.source / 'CMakeLists.txt').read_bytes(), before)

    def test_build_failure_is_recorded_once_and_old_results_are_preserved(self):
        with patch.object(TOOL.subprocess, 'run', return_value=SimpleNamespace(returncode=2)) as run:
            record = TOOL.run(self.args('build', '--config', 'Debug', '--target', 'alpha', '--target', 'beta'))
            self.assertEqual(record['returncode'], 2)
            self.assertEqual(run.call_args.args[0], [sys.executable, '--build', str(self.build),
                '--config', 'Debug', '--target', 'alpha', 'beta'])
            before = {p.name: p.read_bytes() for p in self.report.iterdir()}
            with self.assertRaises(FileExistsError):
                TOOL.run(self.args('build'))
            run.assert_called_once()
            self.assertEqual({p.name: p.read_bytes() for p in self.report.iterdir()}, before)

    def test_test_command_requires_nonempty_ctest_and_real_junit(self):
        with patch.object(TOOL.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            TOOL.run(self.args('test', '--config', 'Release', '--test-regex', '^project-'))
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], [sys.executable, '--test-dir', str(self.build),
            '--output-on-failure', '--no-tests=error', '--output-junit', str(self.report / 'junit.xml'),
            '-C', 'Release', '-R', '^project-'])

    def test_spawn_error_does_not_retry_or_claim_finished(self):
        with patch.object(TOOL.subprocess, 'run', side_effect=OSError('test-owned spawn error')) as run:
            record = TOOL.run(self.args('build'))
        run.assert_called_once()
        self.assertEqual(record['status'], 'ERROR')
        self.assertNotIn('returncode', record)
        self.assertEqual(json.loads((self.report / 'invocation.json').read_text())['status'], 'ERROR')

    def test_invalid_project_parameters_do_not_launch(self):
        with patch.object(TOOL.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError, '--define'):
                TOOL.run(self.args('configure', '--define', 'MISSING_EQUALS'))
            with self.assertRaisesRegex(ValueError, 'absolute executable'):
                TOOL.run(self.args('build', '--cmake', 'cmake'))
            with self.assertRaisesRegex(ValueError, 'separate build'):
                TOOL.run(self.args('configure', '--build-dir', str(self.source)))
        run.assert_not_called()
        self.assertFalse(self.report.exists())

    def test_checker_executes_once_and_evaluates_project_expectation(self):
        def completed(argv, **kwargs):
            self.assertIn('--no-tests=error', argv)
            junit = Path(argv[argv.index('--output-junit') + 1])
            junit.write_text('<testsuite tests="2" failures="0"><testcase name="project-alpha"/>'
                             '<testcase name="project-extra"/></testsuite>')
            return SimpleNamespace(returncode=0)
        with patch.object(CHECK.subprocess, 'run', side_effect=completed) as run:
            result = CHECK.check(self.checker_args(config='Debug', test_regex='project'))
            self.assertEqual(result['status'], 'PASS')
            self.assertEqual(result['checked_tests'], ['project-alpha', 'project-extra'])
            before = {p.name: p.read_bytes() for p in self.report.iterdir()}
            with self.assertRaises(FileExistsError):
                CHECK.check(self.checker_args())
            run.assert_called_once()
            self.assertEqual({p.name: p.read_bytes() for p in self.report.iterdir()}, before)

    def test_checker_zero_process_exit_without_report_is_error(self):
        with patch.object(CHECK.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            result = CHECK.check(self.checker_args())
        run.assert_called_once()
        self.assertEqual(result['status'], 'ERROR')

    def test_no_test_malformed_missing_and_interrupted_reports_never_pass(self):
        for xml, status in [('<testsuite tests="0"/>', 'FINISHED'), ('not XML', 'FINISHED'),
                            ('<other/>', 'FINISHED'), ('<testsuite><testcase name="project-alpha"/></testsuite>', 'STARTED')]:
            with self.subTest(xml=xml, status=status):
                self.assertEqual(self.inspect(xml, status=status)['status'], 'ERROR')
        self.assertEqual(CHECK.inspect_report(self.root / 'absent', {'status': 'FINISHED', 'returncode': 0},
                                            ['project-alpha'])['status'], 'ERROR')

    def test_missing_required_test_and_test_failure_are_assertions(self):
        self.assertEqual(self.inspect('<testsuite><testcase name="wrong-test"/></testsuite>')['status'], 'ASSERTION')
        for code in (0, 8):
            self.assertEqual(self.inspect('<testsuite><testcase name="project-alpha"><failure/></testcase></testsuite>',
                                         code=code)['status'], 'ASSERTION')
        self.assertEqual(self.inspect('<testsuite failures="1"><testcase name="project-alpha"/></testsuite>')['status'], 'ASSERTION')

    def test_skip_error_signal_and_tool_failure_are_errors(self):
        for body in ('<skipped/>', '<error/>'):
            self.assertEqual(self.inspect('<testsuite><testcase name="project-alpha">' + body + '</testcase></testsuite>')['status'], 'ERROR')
        for status in ('notrun', 'disabled'):
            self.assertEqual(self.inspect('<testsuite><testcase name="project-alpha" status="' + status + '"/></testsuite>')['status'], 'ERROR')
        for code in (-15, 8, 127):
            self.assertEqual(self.inspect('<testsuite><testcase name="project-alpha"/></testsuite>', code=code)['status'], 'ERROR')
        self.assertEqual(self.inspect('<testsuite><testcase name="project-alpha"><failure/></testcase></testsuite>', code=127)['status'], 'ERROR')

    def test_suite_errors_duplicates_and_extra_failures_never_pass(self):
        for xml in ('<testsuite errors="1"><testcase name="project-alpha"/></testsuite>',
                    '<testsuite skipped="1"><testcase name="project-alpha"/></testsuite>',
                    '<testsuite skipped="0" disabled="1"><testcase name="project-alpha"/></testsuite>',
                    '<testsuite tests="2"><testcase name="project-alpha"/><testcase name="project-alpha"/></testsuite>',
                    '<testsuite><testcase/></testsuite>'):
            self.assertEqual(self.inspect(xml)['status'], 'ERROR')
        self.assertEqual(self.inspect('<testsuites><testsuite><testcase name="project-alpha"/>'
            '<testcase name="unexpected"><failure/></testcase></testsuite></testsuites>')['status'], 'ASSERTION')

    def test_invalid_expectation_fails_before_any_command(self):
        for document in ({}, {'required_tests': []}, {'required_tests': ['same', 'same']}, {'required_tests': [3]}):
            self.expected.write_text(json.dumps(document))
            with patch.object(CHECK.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    CHECK.check(self.checker_args())
                run.assert_not_called()
        self.assertFalse(self.report.exists())

    def test_inspecting_retained_evidence_never_replays(self):
        with patch.object(CHECK.subprocess, 'run', side_effect=AssertionError('must not replay')):
            result = self.inspect('<testsuite><testcase name="project-alpha"/></testsuite>')
            self.assertEqual(result['status'], 'PASS')

    def test_read_only_inspection_rejects_missing_or_invalid_independent_obligations(self):
        path = self.root / 'junit.xml'
        path.write_text('<testsuite><testcase name="project-alpha"/></testsuite>')
        with patch.object(CHECK.subprocess, 'run', side_effect=AssertionError('must not replay')):
            for required in (None, [], 'project-alpha', ['same', 'same'], [3]):
                with self.subTest(required=required):
                    result = CHECK.inspect_report(path, {'status': 'FINISHED', 'returncode': 0}, required)
                    self.assertEqual(result['status'], 'ERROR')

    def test_structured_bridge_matches_existing_core_pass_assertion_and_error_contract(self):
        from harness_foundry_factory.verification_resources import validate_structured_result
        binding = {'case_id': 'PROJECT-CASE', 'command_id': 'HOST-COMMAND',
                   'network': {'mode': 'NONE'}, 'required_checks': ['project-ctest']}
        for status, code, expected, retry in [('PASS', 0, 'PASS', False),
                ('ASSERTION', 1, 'VALIDATION_FAILED', True), ('ERROR', 2, 'VALIDATION_FAILED', False)]:
            with self.subTest(status=status):
                summary = CHECK.structured_report({'status': status, 'issues': ['test-owned reason']},
                    'project-ctest', 'PROJECT-CASE', 'HOST-COMMAND')
                verdict = validate_structured_result(summary, binding, code)
                self.assertEqual(verdict['status'], expected)
                self.assertIs(verdict['automatic_retry_allowed'], retry)

    def test_structured_cli_writes_host_bound_summary_and_existing_report_never_replays(self):
        report_root = self.root / 'host-report'
        report_root.mkdir()
        argv = ['--ctest', sys.executable, '--build-dir', str(self.build), '--report-dir', str(self.report),
                '--expected', str(self.expected), '--foundry-check-id', 'project-ctest']
        environment = {'FOUNDRY_CASE_ID': 'ACTUAL-CASE', 'FOUNDRY_COMMAND_ID': 'ACTUAL-COMMAND',
                       'FOUNDRY_REPORT_DIR': str(report_root)}
        with patch.dict(os.environ, environment), patch.object(CHECK, 'check', return_value={'status': 'PASS'}) as check:
            with patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(CHECK.main(argv), 0)
            summary = json.loads((report_root / 'summary.json').read_text())
            self.assertEqual(summary['case_id'], 'ACTUAL-CASE')
            self.assertEqual(summary['command_id'], 'ACTUAL-COMMAND')
            self.assertEqual(summary['checks'], [{'id': 'project-ctest', 'status': 'PASS'}])
            before = (report_root / 'summary.json').read_bytes()
            with patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(CHECK.main(argv), 2)
            check.assert_called_once()
            self.assertEqual((report_root / 'summary.json').read_bytes(), before)

    def test_structured_cli_requires_actual_host_identity_before_running(self):
        argv = ['--ctest', sys.executable, '--build-dir', str(self.build), '--report-dir', str(self.report),
                '--expected', str(self.expected), '--foundry-check-id', 'project-ctest']
        with patch.dict(os.environ, {}, clear=True), patch.object(CHECK, 'check') as check:
            with patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(CHECK.main(argv), 2)
            check.assert_not_called()

    def test_resource_execution_requires_checker_and_expectation_in_protected_copy(self):
        verifier = self.root / 'verifier'
        verifier.mkdir()
        protected_expected = verifier / 'expected.json'
        protected_expected.write_bytes(self.expected.read_bytes())
        with patch.dict(os.environ, {'FOUNDRY_VERIFIER_ROOT': str(verifier)}):
            with patch.object(CHECK.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'protected verifier copy'):
                    CHECK.check(self.checker_args(expected=str(protected_expected)))
                with patch.object(CHECK, '__file__', str(verifier / 'check_ctest.py')):
                    with self.assertRaisesRegex(ValueError, 'protected verifier copy'):
                        CHECK.check(self.checker_args())
                run.assert_not_called()
            with patch.object(CHECK, '__file__', str(verifier / 'check_ctest.py')):
                with patch.object(CHECK.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
                    result = CHECK.check(self.checker_args(expected=str(protected_expected)))
                run.assert_called_once()
                self.assertEqual(result['status'], 'ERROR')  # No actual JUnit was produced by this stub.

    def resource_command(self):
        from harness_foundry_factory.build_resource_lifecycle import prepare_resource_invocation
        from harness_foundry_factory.verification_resources import validate_resources
        # Exercise the published profile, not a separate test-only attachment list.
        fragment = json.loads(re.search(r'```json\n(.*?)\n```',
            (PACKAGE / 'guide.md').read_text(), re.S).group(1))
        argv = ['--ctest', sys.executable, '--build-dir', str(self.build),
                '--report-dir', 'resource://report-staging/ctest',
                '--expected', str(self.root / 'verifier/expected.json'),
                '--foundry-check-id', 'ctest-contract']
        profile = {'writable_areas': ['scratch', 'report-staging'], 'network': {'mode': 'NONE'},
                   'services': [], 'retention': {'success': 'REPORTS_ONLY', 'failure_days': 7}, **fragment}
        plan = {'schema_version': '1.2', 'workpacks': [{'verification': [
            {'resource_profile_ref': 'qt', 'argv': argv}]}]}
        verifier = self.root / 'verifier'
        verifier.mkdir(exist_ok=True)
        (verifier / 'check_ctest.py').write_bytes((PACKAGE / 'check_ctest.py').read_bytes())
        (verifier / 'expected.json').write_bytes(self.expected.read_bytes())
        checker = load('capability_qt_archived_check', verifier / 'check_ctest.py')
        config = validate_resources({'schema_version': '1.0', 'root': str(self.root / 'resources'),
            'profiles': {'qt': profile}}, plan, [verifier, self.build, self.source])
        self.resource_index = getattr(self, 'resource_index', 0) + 1
        identity = {'program_id': 'P', 'prepared_event_id': 'PREP', 'attempt_id': 'ATTEMPT',
                    'case_id': 'QT-CASE', 'command_id': 'CMD-' + str(self.resource_index)}
        prepared, failure = prepare_resource_invocation(
            {'phase': 'VERIFICATION', 'executor': 'LOCAL', 'resource_profile_ref': 'qt',
             'argv': argv, 'cwd': str(self.build), 'read_roots': [str(verifier), str(self.build)]},
            config=config, identity=identity, workspace_root=self.source,
            checked_artifacts={}, verifier_files={}, verifier_root=str(verifier))
        self.assertIsNone(failure)
        command = {'command_id': identity['command_id'], 'executor': 'LOCAL',
                   'observation_root': str(self.root / ('observation-' + str(self.resource_index))),
                   'resource_binding': prepared['resource_binding']}
        return checker, prepared, command

    def finish_checker_fixture(self, checker, prepared, command):
        from harness_foundry_factory.process_observation import CommandObservation

        def ctest(argv, **kwargs):
            Path(argv[argv.index('--output-junit') + 1]).write_text(
                '<testsuite><testcase name="project-alpha"/></testsuite>')
            kwargs['stdout'].write(b'test-owned CTest output\n')
            kwargs['stderr'].write(b'test-owned diagnostic\n')
            return SimpleNamespace(returncode=0)

        with patch.dict(os.environ, prepared['environment']), \
             patch.object(checker.subprocess, 'run', side_effect=ctest) as run, \
             patch('sys.stdout', new_callable=io.StringIO):
            code = checker.main(prepared['argv'])
        run.assert_called_once()
        self.assertEqual(code, 0)
        raw = {'status': 'PASS', 'exit_code': code}
        observation = CommandObservation(command['observation_root'], command['command_id'], 'LOCAL')
        observation.finished(raw)
        observation.close()
        return raw

    def test_declared_ctest_reports_survive_cleanup_and_repeated_recovery_without_replay(self):
        from harness_foundry_factory.build_resource_lifecycle import (
            finish_command_observation, recover_command_observation)
        checker, prepared, command = self.resource_command()
        raw = self.finish_checker_fixture(checker, prepared, command)
        binding = command['resource_binding']
        staging = Path(binding['areas']['report-staging'])
        before = {p.relative_to(staging).as_posix(): p.read_bytes()
                  for p in staging.rglob('*') if p.is_file()}
        self.assertEqual(set(before), {'summary.json', 'ctest/invocation.json', 'ctest/junit.xml',
            'ctest/stdout.log', 'ctest/stderr.log', 'ctest/check-result.json'})
        result = finish_command_observation(raw, command)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['resource_cleanup']['status'], 'CLEANED')
        self.assertTrue(all(not Path(area).exists() for area in binding['areas'].values()))
        paths = {report['name']: Path(report['path']) for report in result['resource_reports']}
        self.assertEqual({name: path.read_bytes() for name, path in paths.items()}, before)
        record = json.loads(paths['ctest/invocation.json'].read_text())
        self.assertFalse(Path(record['report_dir']).exists())
        with patch.object(checker.subprocess, 'run', side_effect=AssertionError('no replay')), \
             patch.object(checker, 'check', side_effect=AssertionError('no checker rerun')), \
             patch('harness_foundry_factory.build_resource_lifecycle.allocate_resources',
                   side_effect=AssertionError('no reallocation')), \
             patch('harness_foundry_factory.resource_observation.collect_resource_reports',
                   side_effect=AssertionError('no recollection')), \
             patch('harness_foundry_factory.resource_observation.cleanup_resources',
                   side_effect=AssertionError('no repeated cleanup')):
            for _ in range(2):
                self.assertEqual(recover_command_observation(command), result)
                inspected = checker.inspect_report(paths['ctest/junit.xml'], record,
                    checker.read_expected(self.root / 'verifier/expected.json'))
                self.assertEqual(inspected['status'], 'PASS')
        self.assertEqual({name: path.read_bytes() for name, path in paths.items()}, before)

    def test_missing_declared_raw_attachment_retains_resources_without_replay(self):
        from harness_foundry_factory.build_resource_lifecycle import (
            finish_command_observation, recover_command_observation)
        for missing in ('invocation.json', 'junit.xml', 'stdout.log', 'stderr.log', 'check-result.json'):
            with self.subTest(missing=missing):
                checker, prepared, command = self.resource_command()
                raw = self.finish_checker_fixture(checker, prepared, command)
                binding = command['resource_binding']
                (Path(binding['areas']['report-staging']) / 'ctest' / missing).unlink()
                with patch.object(checker.subprocess, 'run', side_effect=AssertionError('no replay')):
                    result = finish_command_observation(raw, command)
                    self.assertEqual(result['status'], 'VALIDATION_FAILED')
                    self.assertFalse(result['automatic_retry_allowed'])
                    self.assertEqual([error['name'] for error in result['report_errors']], ['ctest/' + missing])
                    self.assertEqual(result['resource_cleanup']['status'], 'RETAINED')
                    self.assertTrue(all(Path(area).is_dir() for area in binding['areas'].values()))
                    self.assertEqual(recover_command_observation(command), result)


if __name__ == '__main__':
    unittest.main()
