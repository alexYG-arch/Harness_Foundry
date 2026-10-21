"""Qt v2 unit/fixture contracts; native Qt evidence is recorded separately."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PACKAGE = Path(__file__).resolve().parents[1] / 'examples/capability-adapters/packages/qt-cmake/2'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ENV = load('qt2_environment_tests', PACKAGE / 'qt_environment.py')
TOOL = load('qt2_bridge_tests', PACKAGE / 'qt_cmake.py')
CHECK = load('qt2_checker_tests', PACKAGE / 'check_ctest.py')


class QtEnvironmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='qt2 环境 ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.sdk = self.root / 'SDK real'
        for relative in ('lib/cmake/Qt6/Qt6Config.cmake', 'lib/cmake/Qt6Core/Qt6CoreConfig.cmake',
                         'lib/cmake/Qt6CoreTools/Qt6CoreToolsTargets.cmake',
                         'lib/QtCore.framework/Versions/A/QtCore'):
            path = self.sdk / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('test-owned file: ' + relative)
        self.tools = {'qt-python': sys.executable, 'cmake': sys.executable, 'ctest': sys.executable}
        self.profile = ENV.discover(self.tools, [str(self.sdk)])['profile']
        self.profile_path = self.root / 'profile.json'
        self.save_profile()
        self.build = self.root / 'build'
        self.build.mkdir()
        self.source = self.root / 'source'
        self.source.mkdir()
        self.report = self.root / 'report'
        self.expected = self.root / 'expected.json'
        self.expected.write_text(json.dumps({'required_tests': ['independent-business-test']}))

    def save_profile(self):
        self.profile_path.write_text(json.dumps(self.profile))

    def command(self, name='configure', *extra):
        argv = [name, '--profile', str(self.profile_path), '--build-dir', str(self.build),
                '--report-dir', str(self.report), *extra]
        if name == 'configure':
            argv.extend(['--source', str(self.source)])
        return TOOL.parser().parse_args(argv)

    def checker_args(self, **changes):
        return SimpleNamespace(**{'profile': str(self.profile_path), 'ctest': None,
            'build_dir': str(self.build), 'report_dir': str(self.report),
            'expected': str(self.expected), 'config': None, 'test_regex': None, 'timeout': 900, **changes})

    def test_manifest_has_namespaced_python_and_shared_public_dependencies_only(self):
        descriptor = json.loads((PACKAGE / 'capability.json').read_text())
        self.assertEqual(descriptor['version'], '2')
        self.assertEqual({tool['interpreter'] for tool in descriptor['tools']}, {'qt-python'})
        self.assertNotIn('python', [row['id'] for row in descriptor['environment']])
        self.assertIn('check_ctest.py', descriptor['verification_files'])
        shared = [row['path'] for row in descriptor['verification_files'] if isinstance(row, dict) and row['shared']]
        self.assertEqual(set(shared), {'qt_environment.py', 'stack_runtime.py', 'native_dependencies.py'})
        for name in ('stack_runtime.py', 'native_dependencies.py'):
            self.assertEqual((PACKAGE / name).read_bytes(), (PACKAGE.parents[2] / name).read_bytes())
        public = [*descriptor['materials'], *descriptor['runtime_files'], *(row['path'] for row in descriptor['tools'])]
        self.assertNotIn('check_ctest.py', public)
        for path in public:
            self.assertTrue((PACKAGE / path).is_file(), path)

    def test_discovery_is_pure_and_parent_aliases_select_same_sdk(self):
        alias = self.root / 'SDK alias'
        alias.symlink_to(self.sdk, target_is_directory=True)
        with patch.object(ENV.runtime, 'run_capture', side_effect=AssertionError('no process')):
            result = ENV.discover(self.tools, [str(alias), str(self.sdk)])
        self.assertEqual(result['status'], 'READY')
        self.assertFalse(result['probes_executed'])
        self.assertEqual(result['profile']['extensions']['qt']['sdk'], str(self.sdk))
        self.assertEqual(result['profile']['tools']['qt-python'], sys.executable)

    def test_missing_and_ambiguous_sdks_are_diagnosed(self):
        second = self.root / 'second-sdk'
        shutil.copytree(self.sdk, second)
        self.assertEqual(ENV.discover(self.tools, [str(self.sdk), str(second)])['status'], 'INCOMPLETE')
        result = ENV.discover(self.tools, [str(self.root / 'missing')])
        self.assertEqual(result['status'], 'INCOMPLETE')
        self.assertTrue(result['diagnostics'])
        with self.assertRaisesRegex(ValueError, 'absolute'):
            ENV.discover({**self.tools, 'cmake': 'cmake'}, [str(self.sdk)])

    def test_profile_package_and_qt_metadata_binding_are_checked(self):
        self.profile['package']['version'] = '1'
        self.save_profile()
        with self.assertRaisesRegex(ValueError, 'package/version'):
            ENV.load_profile(self.profile_path)
        self.profile['package']['version'] = '2'
        self.profile['extensions']['qt']['cmake_dir'] = str(self.root)
        self.save_profile()
        with self.assertRaisesRegex(ValueError, 'CMake directory'):
            ENV.load_profile(self.profile_path)

    def test_configure_pins_metadata_and_preserves_project_definitions(self):
        with patch.object(TOOL.runtime, 'run_capture', return_value={'status': 'FINISHED', 'returncode': 0}) as run:
            TOOL.run(self.command('configure', '--define', 'PROJECT_LABEL=custom', '--config', 'Debug'))
        argv = run.call_args.args[0]
        self.assertIn('-DPROJECT_LABEL=custom', argv)
        self.assertIn('-DQt6_DIR:PATH=' + str(self.sdk / 'lib/cmake/Qt6'), argv)
        self.assertIn('-DQt6Core_DIR:PATH=' + str(self.sdk / 'lib/cmake/Qt6Core'), argv)
        self.assertNotIn('CMAKE_PREFIX_PATH', '\n'.join(argv))
        self.assertEqual(run.call_args.kwargs['timeout'], 900)
        run.assert_called_once()

    def test_conflicting_qt_tool_or_duplicate_definitions_do_not_execute(self):
        for extra in (('--define', 'Qt6_DIR=/other/sdk'),
                      ('--define', 'X=1', '--define', 'X=2'), ('--cmake', '/other/cmake')):
            with self.subTest(extra=extra), patch.object(TOOL.runtime, 'run_capture') as run:
                with self.assertRaises(ValueError):
                    TOOL.run(self.command('configure', *extra))
                run.assert_not_called()

    def test_preset_runs_from_source_and_keeps_explicit_metadata_precedence(self):
        self.profile['environment'] = {'set': {'QT_TEST_MARKER': 'profile'}, 'prepend': {'PATH': [str(self.sdk / 'bin')]}}
        self.save_profile()
        with patch.dict(os.environ, {'QT_TEST_MARKER': 'outer'}):
            with patch.object(TOOL.runtime, 'run_capture', return_value={}) as run:
                TOOL.run(self.command('configure', '--preset', 'selected-preset'))
            self.assertEqual(os.environ['QT_TEST_MARKER'], 'outer')
        self.assertEqual(run.call_args.kwargs['cwd'], str(self.source))
        self.assertIn('selected-preset', run.call_args.args[0])
        self.assertEqual(run.call_args.kwargs['env']['QT_TEST_MARKER'], 'profile')
        self.assertTrue(run.call_args.kwargs['env']['PATH'].startswith(str(self.sdk / 'bin')))

    def test_old_report_is_not_overwritten_or_replayed(self):
        self.report.mkdir()
        marker = self.report / 'old.json'
        marker.write_text('old evidence')
        with patch.object(TOOL.runtime, 'run_capture') as run:
            with self.assertRaises(FileExistsError):
                TOOL.run(self.command('build'))
            run.assert_not_called()
        self.assertEqual(marker.read_text(), 'old evidence')

    def query_stub(self, argv, cwd, report_dir, **kwargs):
        report = Path(report_dir)
        report.mkdir()
        if argv[-1] == '--version':
            output = 'cmake version 3.31.12-vendor\n'
        elif argv[-1] == '-query':
            output = 'QT_VERSION:6.11.1\nQT_INSTALL_PREFIX:' + str(self.root) + '\n'
        else:
            item = Path(argv[-1])
            dependency = getattr(self, 'dependency', None)
            output = str(item) + ':\n'
            if dependency is not None and item != dependency:
                output += '\t' + str(dependency) + ' (compatibility version 1.0.0, current version 1.0.0)\n'
        (report / 'stdout.txt').write_text(output)
        (report / 'stderr.txt').write_text('')
        return {'status': 'FINISHED', 'returncode': 0}

    def test_observe_preserves_raw_versions_and_shared_qmake_prefix(self):
        self.profile['tools']['qmake'] = sys.executable
        with patch.object(ENV.runtime, 'run_capture', side_effect=self.query_stub) as run:
            result = ENV.observe(self.profile, self.report)
        self.assertEqual(result['status'], 'OBSERVED')
        self.assertEqual(run.call_count, 3)
        qt = result['profile']['extensions']['qt']
        self.assertIn('-vendor', qt['observed_versions']['cmake'])
        self.assertFalse(qt['qmake_prefix_matches_selected_sdk'])
        self.assertFalse(result['native_probe'])

    def test_selected_dependency_closure_generates_loader_dirs_without_sdk_scan(self):
        self.dependency = self.root / 'Dependency dir/libexample.dylib'
        self.dependency.parent.mkdir()
        self.dependency.write_text('actual dependency fixture')
        self.profile['tools']['otool'] = sys.executable
        with patch.object(ENV.runtime, 'run_capture', side_effect=self.query_stub), patch.object(ENV.platform, 'system', return_value='Darwin'):
            result = ENV.observe(self.profile, self.report, adapt_loader_paths=True)
        self.assertEqual(result['status'], 'OBSERVED')
        profile = result['profile']
        self.assertIn(str(self.dependency.parent), profile['environment']['prepend']['DYLD_LIBRARY_PATH'])
        self.assertIn(str(self.sdk / 'lib'), profile['environment']['prepend']['DYLD_FRAMEWORK_PATH'])
        self.assertTrue(any(row['path'] == str(self.dependency) for row in profile['observations']))
        self.assertNotIn(str(self.root), profile['read_paths'])

    def test_unresolved_dependencies_or_loader_environment_conflict_are_explicit(self):
        with self.assertRaisesRegex(ValueError, 'unresolved'):
            ENV._dependency_path('@rpath/missing.dylib', self.sdk / 'lib/QtCore', [])
        self.profile['tools']['otool'] = sys.executable
        self.profile['environment']['set']['DYLD_LIBRARY_PATH'] = '/project/chosen'
        with patch.object(ENV.runtime, 'run_capture', side_effect=self.query_stub), patch.object(ENV.platform, 'system', return_value='Darwin'):
            result = ENV.observe(self.profile, self.report, adapt_loader_paths=True)
        self.assertEqual(result['status'], 'ERROR')
        self.assertIsNone(result['profile'])
        self.assertTrue(any('conflict' in issue for issue in result['issues']))

    def test_environment_probe_failure_does_not_spawn_later_steps_or_retry(self):
        with patch.object(ENV.runtime, 'run_capture', return_value={'status': 'FINISHED', 'returncode': 3}) as run:
            result = ENV.probe(self.profile, self.root / 'probe', self.report, receiver='fixture-only')
        self.assertEqual(result['status'], 'ERROR')
        self.assertFalse(result['complete'])
        run.assert_called_once()
        with patch.object(ENV.runtime, 'run_capture') as run:
            with self.assertRaises(FileExistsError):
                ENV.probe(self.profile, self.root / 'probe', self.report, receiver='fixture-only')
            run.assert_not_called()

    def test_probe_no_tests_or_wrong_cli_output_cannot_pass(self):
        def capture(argv, cwd, report_dir, **kwargs):
            report = Path(report_dir)
            report.mkdir()
            (report / 'stdout.txt').write_text('QtCore:3' if report.name == 'run' else '')
            if report.name == 'test':
                (report / 'junit.xml').write_text('<testsuite tests="0"/>')
            return {'status': 'FINISHED', 'returncode': 0}
        with patch.object(ENV.runtime, 'run_capture', side_effect=capture) as run:
            result = ENV.probe(self.profile, self.root / 'probe', self.report, receiver='fixture-only')
        self.assertEqual(run.call_count, 4)
        self.assertEqual(result['status'], 'ERROR')
        self.assertIn('CTest report', result['issues'][0])

    def test_protected_checker_refuses_outside_helpers_before_import(self):
        verifier = self.root / 'protected'
        verifier.mkdir()
        with patch.dict(os.environ, {'FOUNDRY_VERIFIER_ROOT': str(verifier)}), patch.object(CHECK, '_environment_module') as loaded:
            with self.assertRaisesRegex(ValueError, 'protected verifier'):
                CHECK.check(self.checker_args())
            loaded.assert_not_called()

    def test_protected_checker_uses_own_helper_and_profile_not_product_copy(self):
        verifier = self.root / 'protected'
        verifier.mkdir()
        for name in ('check_ctest.py', 'qt_environment.py', 'stack_runtime.py', 'native_dependencies.py'):
            shutil.copyfile(PACKAGE / name, verifier / name)
        shutil.copyfile(self.profile_path, verifier / 'profile.json')
        shutil.copyfile(self.expected, verifier / 'expected.json')
        protected = load('qt2_protected_test', verifier / 'check_ctest.py')
        module = protected._environment_module()
        self.assertEqual(Path(module.__file__).parent, verifier)
        self.assertEqual(Path(module.runtime.__file__).parent, verifier)
        def capture(argv, **kwargs):
            report = Path(kwargs['report_dir'])
            report.mkdir()
            Path(argv[argv.index('--output-junit') + 1]).write_text('<testsuite><testcase name="independent-business-test"><failure/></testcase></testsuite>')
            return {'status': 'FINISHED', 'returncode': 8}
        with patch.dict(os.environ, {'FOUNDRY_VERIFIER_ROOT': str(verifier)}), patch.object(protected, '_environment_module', return_value=module), patch.object(module.runtime, 'run_capture', side_effect=capture) as run:
            result = protected.check(self.checker_args(profile=str(verifier / 'profile.json'), expected=str(verifier / 'expected.json')))
        run.assert_called_once()
        self.assertEqual(result['status'], 'ASSERTION')
        self.assertEqual(run.call_args.kwargs['metadata']['profile_sha256'], module.runtime.profile_digest(self.profile))

    def test_public_runtime_probe_does_not_depend_on_private_checker(self):
        self.assertNotIn("_sibling('check_ctest')", (PACKAGE / 'qt_environment.py').read_text())
        self.assertIn('QtCore/QList', (PACKAGE / 'probe-main.cpp').read_text())

    def test_read_retained_ctest_keeps_assertion_without_execution(self):
        junit = self.root / 'junit.xml'
        junit.write_text('<testsuite><testcase name="independent-business-test"><failure/></testcase></testsuite>')
        with patch.object(CHECK, 'check', side_effect=AssertionError('no replay')):
            for _ in range(2):
                self.assertEqual(CHECK.inspect_report(junit, {'status': 'FINISHED', 'returncode': 8}, ['independent-business-test'])['status'], 'ASSERTION')

    def captured_probe(self):
        self.report.mkdir()
        operations = []
        for operation in ('configure', 'build', 'test', 'run'):
            directory = self.report / operation
            directory.mkdir()
            record = {'format_version': 1, 'kind': 'stack-command-capture', 'status': 'FINISHED',
                'complete': True, 'returncode': 0, 'stdout': 'stdout.txt', 'stderr': 'stderr.txt',
                'metadata': {'operation': operation, 'package': ENV.PACKAGE}}
            (directory / 'invocation.json').write_text(json.dumps(record))
            (directory / 'stdout.txt').write_text('QtCore:3\n' if operation == 'run' else '')
            (directory / 'stderr.txt').write_text('')
            operations.append({'operation': operation, 'path': str(directory), 'record': record})
        (self.report / 'test/junit.xml').write_text('<testsuite><testcase name="qt-environment-probe" status="run"/></testsuite>')
        (self.report / 'probe.json').write_text(json.dumps({'status': 'ERROR', 'complete': False,
            'profile_sha256': ENV.runtime.profile_digest(self.profile), 'receiver': 'actual-test-receiver',
            'operations': operations, 'issues': ['historical final-summary failure']}))

    def test_complete_probe_capture_is_retrieved_without_replay_or_overwrite(self):
        self.captured_probe()
        before = {p.relative_to(self.report).as_posix(): p.read_bytes() for p in self.report.rglob('*') if p.is_file()}
        with patch.object(ENV.runtime, 'run_capture', side_effect=AssertionError('no replay')):
            for _ in range(2):
                result = ENV.inspect_probe(self.profile, self.report, receiver='actual-test-receiver')
                self.assertEqual(result['status'], 'PASS')
                self.assertTrue(result['complete'])
        after = {p.relative_to(self.report).as_posix(): p.read_bytes() for p in self.report.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(ENV.runtime.reuse_probe(self.profile, result, 'actual-test-receiver')['decision'], 'UNKNOWN')

    def test_recovery_does_not_accept_wrong_binding_or_missing_capture(self):
        self.captured_probe()
        with patch.object(ENV.runtime, 'run_capture', side_effect=AssertionError('no replay')):
            self.assertEqual(ENV.inspect_probe(self.profile, self.report, receiver='other-receiver')['status'], 'ERROR')
            (self.report / 'build/stdout.txt').unlink()
            self.assertEqual(ENV.inspect_probe(self.profile, self.report, receiver='actual-test-receiver')['status'], 'ERROR')

    def test_protected_helper_symlink_escape_is_rejected_before_loading(self):
        verifier = self.root / 'protected'
        verifier.mkdir()
        shutil.copyfile(PACKAGE / 'check_ctest.py', verifier / 'check_ctest.py')
        shutil.copyfile(PACKAGE / 'stack_runtime.py', verifier / 'stack_runtime.py')
        shutil.copyfile(PACKAGE / 'native_dependencies.py', verifier / 'native_dependencies.py')
        (verifier / 'qt_environment.py').symlink_to(PACKAGE / 'qt_environment.py')
        shutil.copyfile(self.profile_path, verifier / 'profile.json')
        shutil.copyfile(self.expected, verifier / 'expected.json')
        protected = load('qt2_symlink_checker', verifier / 'check_ctest.py')
        with patch.dict(os.environ, {'FOUNDRY_VERIFIER_ROOT': str(verifier)}), patch.object(protected, '_environment_module') as loaded:
            with self.assertRaisesRegex(ValueError, 'protected verifier'):
                protected.check(self.checker_args(profile=str(verifier / 'profile.json'), expected=str(verifier / 'expected.json')))
            loaded.assert_not_called()

    def test_native_helper_handles_cycles_once_and_keeps_system_cache_entries(self):
        core = Path(self.profile['extensions']['qt']['core_library'])
        dependency = self.root / 'libdependent.dylib'
        dependency.write_text('fixture dependency')
        def query(argv, cwd, report_dir, **kwargs):
            report = Path(report_dir)
            report.mkdir()
            item = Path(argv[-1])
            target = dependency if item == core else core
            (report / 'stdout.txt').write_text(str(item) + ':\n\t' + str(target)
                + ' (compatibility version 1.0.0, current version 1.0.0)\n'
                + '\t/usr/lib/dyld-cache-only.dylib (compatibility version 1.0.0, current version 1.0.0)\n')
            return {'status': 'FINISHED', 'returncode': 0}
        with patch.object(ENV.runtime, 'run_capture', side_effect=query) as run:
            result = ENV.native_dependencies.discover_dependencies([str(core), str(core)],
                tool=sys.executable, report_dir=self.report, environment={}, runtime=ENV.runtime)
        self.assertEqual(result['status'], 'OBSERVED')
        self.assertTrue(result['complete'])
        self.assertEqual(run.call_count, 2)
        self.assertEqual(len(result['files']), 2)
        with patch.object(ENV.runtime, 'run_capture') as run:
            with self.assertRaises(FileExistsError):
                ENV.native_dependencies.discover_dependencies([str(core)], tool=sys.executable,
                    report_dir=self.report, environment={}, runtime=ENV.runtime)
            run.assert_not_called()

    def test_selected_aliases_propose_only_real_lookup_parents(self):
        lookup = self.root / 'lookup'
        lookup.mkdir()
        real = self.root / 'selected-libraries'
        real.mkdir()
        (real / 'a.dylib').write_text('selected a')
        (real / 'b.dylib').write_text('selected b')
        (lookup / 'one').symlink_to('../selected-libraries', target_is_directory=True)
        (lookup / 'two').symlink_to('../selected-libraries', target_is_directory=True)
        unrelated = lookup / 'unselected'
        unrelated.symlink_to(self.root / 'missing-unselected')
        core = Path(self.profile['extensions']['qt']['core_library'])
        def query(argv, cwd, report_dir, **kwargs):
            report = Path(report_dir)
            report.mkdir()
            if argv[-1] == '--version':
                output = 'cmake version 3.31.12\n'
            else:
                item = Path(argv[-1])
                output = str(item) + ':\n'
                if item == core:
                    for path in (lookup / 'one/a.dylib', lookup / 'two/b.dylib'):
                        output += '\t' + str(path) + ' (compatibility version 1.0.0, current version 1.0.0)\n'
            (report / 'stdout.txt').write_text(output)
            return {'status': 'FINISHED', 'returncode': 0}
        self.profile['tools']['otool'] = sys.executable
        old_reads = list(self.profile['read_paths'])
        with patch.object(ENV.runtime, 'run_capture', side_effect=query) as called:
            result = ENV.observe(self.profile, self.report)
        self.assertEqual(result['status'], 'OBSERVED', result['issues'])
        self.assertEqual(called.call_count, 5)  # two versions, core, two selected libraries
        self.assertEqual(result['read_path_proposals'], [str(lookup)])
        aliases = result['profile']['extensions']['path_aliases']
        self.assertEqual({row['path'] for row in aliases}, {str(lookup / 'one'), str(lookup / 'two')})
        self.assertTrue(all(row['status'] == 'OBSERVED' for row in aliases))
        self.assertNotIn(str(unrelated), str(aliases))
        self.assertIn(str(lookup), result['profile']['read_paths'])
        self.assertNotIn(str(self.root), result['profile']['read_paths'])
        self.assertEqual(self.profile['read_paths'], old_reads)

    def test_alias_denial_and_broken_target_keep_partial_capture_without_retry(self):
        core = Path(self.profile['extensions']['qt']['core_library'])
        lookup = self.root / 'lookup'
        lookup.mkdir()
        alias = lookup / 'selected'
        alias.symlink_to(self.root / 'absent', target_is_directory=True)
        def query(argv, cwd, report_dir, **kwargs):
            directory = Path(report_dir)
            directory.mkdir()
            (directory / 'stdout.txt').write_text(str(core) + ':\n\t' + str(alias / 'lib.dylib')
                + ' (compatibility version 1.0.0, current version 1.0.0)\n')
            return {'status': 'FINISHED', 'returncode': 0}
        with patch.object(ENV.runtime, 'run_capture', side_effect=query) as called:
            result = ENV.native_dependencies.discover_dependencies([str(core)], tool=sys.executable,
                report_dir=self.report, environment={}, runtime=ENV.runtime)
        self.assertEqual(result['status'], 'ERROR')
        self.assertEqual(called.call_count, 1)
        self.assertEqual(len(result['files']), 1)
        self.assertEqual(result['aliases'][0]['status'], 'UNAVAILABLE')
        self.assertEqual(result['read_path_proposals'], [str(lookup)])
        lstat = Path.lstat
        def denied(path, *args, **kwargs):
            if path == alias:
                raise PermissionError(1, 'Operation not permitted', str(path))
            return lstat(path, *args, **kwargs)
        with patch.object(ENV.runtime, 'run_capture', side_effect=query) as called, patch.object(Path, 'lstat', denied):
            failed = ENV.native_dependencies.discover_dependencies([str(core)], tool=sys.executable,
                report_dir=self.root / 'denied-report', environment={}, runtime=ENV.runtime)
        self.assertEqual(failed['status'], 'ERROR')
        self.assertEqual(called.call_count, 1)
        self.assertIn('Operation not permitted', failed['issues'][0])
        self.assertEqual(len(failed['operations']), 1)

    def test_link_chain_in_selected_load_path_is_observed_without_scanning(self):
        lookup = self.root / 'lookup'
        lookup.mkdir()
        real = self.root / 'real'
        real.mkdir()
        library = real / 'library.dylib'
        library.write_text('selected')
        (lookup / 'first').symlink_to('second')
        (lookup / 'second').symlink_to('../real', target_is_directory=True)
        aliases, proposed = [], []
        result = ENV.native_dependencies.dependency_path(str(lookup / 'first/library.dylib'), self.sdk,
            [], aliases=aliases, read_path_proposals=proposed, runtime=ENV.runtime)
        self.assertEqual(result, library)
        self.assertEqual([row['path'] for row in aliases], [str(lookup / 'first'), str(lookup / 'second')])
        self.assertEqual(proposed, [str(lookup)])

    def test_native_helper_rejects_ambiguous_rpath_and_non_macho_output(self):
        directories = [self.root / 'a', self.root / 'b']
        for directory in directories:
            directory.mkdir()
            (directory / 'same.dylib').write_text('different native file')
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            ENV.native_dependencies.dependency_path('@rpath/same.dylib', self.sdk / 'owner', directories)
        def invalid(argv, cwd, report_dir, **kwargs):
            directory = Path(report_dir)
            directory.mkdir()
            (directory / 'stdout.txt').write_text('not a Mach-O file header')
            return {'status': 'FINISHED', 'returncode': 0}
        with patch.object(ENV.runtime, 'run_capture', side_effect=invalid) as run:
            result = ENV.native_dependencies.discover_dependencies(
                [self.profile['extensions']['qt']['core_library']], tool=sys.executable,
                report_dir=self.report, environment={}, runtime=ENV.runtime)
        run.assert_called_once()
        self.assertEqual(result['status'], 'ERROR')
        self.assertFalse(result['complete'])
        self.assertTrue((self.report / 'dependencies.json').is_file())

    def test_bound_compiler_is_pinned_without_changing_other_stack_interpreter(self):
        self.profile['tools']['compiler'] = sys.executable
        self.save_profile()
        with patch.object(TOOL.runtime, 'run_capture', return_value={}) as run:
            TOOL.run(self.command())
        self.assertIn('-DCMAKE_CXX_COMPILER:PATH=' + sys.executable, run.call_args.args[0])
        self.assertNotIn('python', self.profile['tools'])


if __name__ == '__main__':
    unittest.main()
