"""Opt-in real stack receivers and resource recovery; no model or Program.

Evidence is kept under HFFACTORY_STACK_NATIVE_ROOT when supplied. Every run owns
a fresh leaf; neither accepted targets nor WP10 state are used or changed.
"""

from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import venv
from uuid import uuid4

from harness_foundry_factory.local_process import CodexSandboxRunner, LocalCommand
from harness_foundry_factory.resource_observation import finish_resource_observation
from harness_foundry_factory.verification_resources import allocate_resources


ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / 'examples/capability-adapters/packages'


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def digests(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}


CHECKER = r'''import argparse, errno, importlib.util, json, os, socket
from pathlib import Path

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

p = argparse.ArgumentParser()
p.add_argument('--protected', required=True)
p.add_argument('--project', required=True)
p.add_argument('--input', required=True)
p.add_argument('--receiver', required=True)
p.add_argument('--forbidden-source', required=True)
p.add_argument('--qt', action='store_true')
a = p.parse_args()
root, scratch, reports = Path(a.protected), Path(os.environ['FOUNDRY_SCRATCH_DIR']), Path(os.environ['FOUNDRY_REPORT_DIR'])
assert Path(os.environ['FOUNDRY_VERIFIER_ROOT']).resolve() == root.resolve()
expected = json.loads((root / 'expected.json').read_text())
checks, detail = [], {}
if a.qt:
    qt = load(root / 'qt/qt_environment.py', 'protected_qt')
    assert Path(qt.__file__).parent == root / 'qt'
    profile = qt.load_profile(root / 'qt/profile.json')
    observed = qt.probe(profile, scratch / 'qt-work', reports / 'qt', receiver=json.loads(Path(a.receiver).read_text()))
    assert observed['status'] == 'PASS', observed
    assert (reports / 'qt/run/stdout.txt').read_text().strip() == expected['qt_output']
    checks.append({'id':'qt', 'status':'PASS'})
    detail['qt'] = {'helper':qt.__file__, 'runtime':qt.runtime.__file__, 'profile':qt.runtime.profile_digest(profile)}
py = load(root / 'python/check_python.py', 'protected_python')
args = argparse.Namespace(profile=str(root / 'python/profile.json'), input=a.input,
    expected=str(root / 'python/expected.json'), cwd=str(scratch), report_dir=str(reports / 'python'),
    recover=False, receiver=a.receiver, timeout=180)
observed = py.check(args)
assert observed['status'] == 'PASS', observed
assert observed['observation']['calculation'] == expected['calculation']
checks.append({'id':'python', 'status':'PASS'})
detail['python'] = {'helper':py.__file__, 'runtime':py.runtime.__file__, 'observation':observed['observation']}
denied = []
for target in [root / 'expected.json', Path(a.project) / 'forbidden.txt']:
    try:
        with target.open('a') as stream: stream.write('unexpected write')
    except OSError as error:
        assert error.errno in (errno.EPERM, errno.EACCES, errno.EROFS), repr(error)
        denied.append(str(target))
    else:
        raise AssertionError('read-only input writable: ' + str(target))
with socket.socket() as connection:
    connection.settimeout(1)
    try:
        connection.connect(('127.0.0.1', 9))
    except OSError as error:
        assert error.errno in (errno.EPERM, errno.EACCES), 'NONE network unexpectedly reached socket: ' + repr(error)
    else:
        raise AssertionError('NONE network unexpectedly connected')
checks.append({'id':'permissions', 'status':'PASS'})
try:
    Path(a.forbidden_source).read_bytes()
except OSError as error:
    assert error.errno in (errno.EPERM, errno.EACCES), repr(error)
else:
    raise AssertionError('developer source unexpectedly readable')
result = {'schema_version':'1.0', 'case_id':os.environ['FOUNDRY_CASE_ID'], 'command_id':os.environ['FOUNDRY_COMMAND_ID'],
          'status':'CHECKS_PASS', 'checks':checks, 'errors':[], 'denied_writes':denied, 'loaded':detail}
(reports / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps({'status':'PASS', 'checks':checks}))
'''


@unittest.skipUnless(os.environ.get('HFFACTORY_TEST_CODEX_SANDBOX'), 'native receiver opt-in required')
class StackEnvironmentNativeTests(unittest.TestCase):
    def setUp(self):
        parent = Path(os.environ.get('HFFACTORY_STACK_NATIVE_ROOT', ROOT / 'runs/stack-environment-native'))
        parent.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix=self._testMethodName + '-', dir=parent)).resolve()
        self.runner = CodexSandboxRunner(os.environ['HFFACTORY_TEST_CODEX_SANDBOX'], output_limit_bytes=131072)
        self.commands = []
        self.public, self.protected, self.project = [self.root / name for name in ('public', 'protected', 'project')]
        for directory in (self.public, self.protected, self.project):
            directory.mkdir()
        self.reads = [Path(sys.base_prefix), Path(sys._base_executable).parent,
                      *map(Path, json.loads(os.environ.get('HFFACTORY_TEST_PYTHON_READ_ROOTS', '[]')))]
        self.helper = self.new_venv('helper venv')
        self.python = self.new_venv('project venv')
        self.reads += [self.helper.parent.parent, self.python.parent.parent]
        self.project.joinpath('local_values.py').write_text('VALUE = 23\n')
        self.input = self.root / 'input.json'
        write_json(self.input, {'schema_version':'1', 'modules':['local_values'],
                               'decimal_values':['0.10', '0.20'], 'sqlite_values':[2, 3]})
        self.py = module(PACKAGES / 'python-environment/1/python_environment.py', 'native_py_env')
        self.py_profile = self.py.bind(str(self.python), [str(self.project)], [str(self.project / 'local_values.py')])
        if self._testMethodName not in {'test_python_delivery_new_directory_new_input_and_environment',
                                       'test_native_timed_out_stack_command_stops_owned_child_and_keeps_capture'}:
            self.py_profile = self.observe_python(self.py_profile, 'host-selected-python-observation')
        for target in (self.public / 'python', self.protected / 'python'):
            shutil.copytree(PACKAGES / 'python-environment/1', target,
                            ignore=shutil.ignore_patterns('check_python.py') if target.parent == self.public else None)
            write_json(target / 'profile.json', self.py_profile)
        self.calculation = {'decimal_sum':'0.30', 'sqlite_count':2, 'sqlite_sum':5}
        self.expectation()
        self.protected.joinpath('checker.py').write_text(CHECKER)

    def new_venv(self, name):
        directory = self.root / name
        venv.EnvBuilder(with_pip=False, symlinks=True, system_site_packages=False).create(directory)
        return directory / 'bin/python'

    def observe_python(self, profile, label):
        observed = self.py.observe_native(profile, self.input, self.root / label,
            otool='/usr/bin/otool', adapt_loader_paths=True, timeout=60)
        self.assertEqual(observed['status'], 'OBSERVED', observed)
        self.assertFalse(observed['native_import_verified'])
        self.reads.extend(map(Path, observed['profile']['read_paths']))
        return observed['profile']

    def expectation(self):
        write_json(self.protected / 'python/expected.json', {
            'schema_version':'1', 'python':{'prefix':str(self.python.parent.parent), 'require_venv':True, 'version_min':[3,11]},
            'modules':{'local_values':{'origin_root':str(self.project)}}, 'calculation':self.calculation})
        write_json(self.protected / 'expected.json', {'qt_output':'QtCore:3', 'calculation':self.calculation})

    def native(self, argv, cwd, reads, writes, label, environment=None, expected_status='PASS'):
        command = LocalCommand.prepare(argv=list(map(str, argv)), cwd=cwd,
            read_roots=[*self.reads, *reads], write_roots=writes, environment=environment,
            network={'mode':'NONE'}, timeout_seconds=300)
        record = {'argv':list(command.argv), 'cwd':str(command.cwd), 'permission_profile':command.permission_profile(),
                  'network':command.network, 'writes':list(map(str, command.write_roots))}
        self.commands.append(record)
        started = time.monotonic()
        result = self.runner.run(command)
        record["elapsed_seconds"] = time.monotonic() - started
        write_json(self.root / (label + '-receiver.json'), {**record, 'result':result})
        self.assertEqual(result['status'], expected_status, result)
        self.assertEqual(result['receiver'], 'CODEX_SANDBOX_PERMISSION_PROFILE')
        self.assertEqual(result['effective_network_policy']['mode'], 'NONE')
        return result

    def python_producer(self, label='producer'):
        work = self.root / (label + '-work')
        work.mkdir()
        report = work / 'python-capture'
        argv = [self.helper, '-I', '-B', self.public / 'python/python_environment.py', 'probe',
                '--profile', self.public / 'python/profile.json', '--input', self.input,
                '--cwd', work, '--report-dir', report, '--timeout', '180']
        self.native(argv, work, [self.public, self.project, self.input], [work], label,
                    {'TMPDIR':str(work)})
        observation = json.loads((report / 'observation.json').read_text())
        self.assertEqual(observation['python']['prefix'], str(self.python.parent.parent))
        self.assertNotEqual(observation['python']['prefix'], str(self.helper.parent.parent))
        self.assertEqual(observation['calculation'], self.calculation)
        return report

    def verification(self, *, qt=False):
        reports = ['summary.json', 'python/invocation.json', 'python/stdout.txt', 'python/stderr.txt', 'python/observation.json']
        if qt:
            reports += ['qt/probe.json', 'qt/test/junit.xml']
            reports += [f'qt/{step}/{name}' for step in ('configure','build','test','run')
                        for name in ('invocation.json','stdout.txt','stderr.txt')]
        identity = {'program_id':'ENGINEERING-FIXTURE-NOT-A-PROGRAM', 'prepared_event_id':'ENGINEERING-NOT-A-GRANT',
                    'attempt_id':'FIXTURE-NOT-AN-ATTEMPT', 'case_id':'STACKS', 'command_id':'COMMAND-' + uuid4().hex}
        config = {'root':str(self.root / 'resources'), 'profiles':{'stack':{
            'writable_areas':['scratch','report-staging'], 'network':{'mode':'NONE'}, 'services':[],
            'result_protocol':'STRUCTURED_V1', 'required_checks':(['qt'] if qt else []) + ['python','permissions'],
            'report_files':reports, 'retention':{'success':'REPORTS_ONLY', 'failure_days':7}}}}
        binding = allocate_resources(config, 'stack', identity)
        binding['env']['FOUNDRY_VERIFIER_ROOT'] = str(self.protected)
        receiver = self.root / 'receiver-declaration.json'
        write_json(receiver, {'receiver':'CODEX_SANDBOX_PERMISSION_PROFILE', 'network':'NONE',
                             'read_roots':list(map(str, [*self.reads, self.protected, self.project, self.input])),
                             'write_roots':binding['write_roots']})
        argv = [self.helper, '-I', '-B', self.protected / 'checker.py', '--protected', self.protected,
                '--project', self.project, '--input', self.input, '--receiver', receiver,
                '--forbidden-source', PACKAGES / 'python-environment/1/python_environment.py']
        if qt: argv.append('--qt')
        before = digests(self.protected)
        raw = self.native(argv, self.project, [self.protected,self.project,self.input,receiver],
                          binding['write_roots'], 'protected', binding['env'])
        self.assertEqual(digests(self.protected), before)
        observation = self.root / 'host-observation'
        result = finish_resource_observation(raw, binding, observation)
        self.assertEqual(result['status'], 'PASS', result)
        self.assertEqual(result['resource_cleanup']['status'], 'CLEANED')
        self.assertTrue(all(not Path(p).exists() for p in binding['areas'].values()))
        archived = digests(observation / 'reports')
        count = len(self.commands)
        recovered = finish_resource_observation(raw, binding, observation)
        self.assertEqual(recovered['status'], 'PASS')
        self.assertEqual(len(self.commands), count, 'captured recovery must not dispatch another command')
        self.assertEqual(digests(observation / 'reports'), archived)
        self.assertEqual({r['name'] for r in recovered['resource_reports']}, set(reports))
        for invocation in (observation / 'reports').rglob('invocation.json'):
            captured = json.loads(invocation.read_text())
            if captured.get('pid'):
                with self.assertRaises(ProcessLookupError, msg='owned completed process group must be gone'):
                    os.killpg(captured['pid'], 0)
        self.assertTrue(self.public.is_dir())
        self.assertTrue(self.protected.is_dir())
        self.assertTrue(self.python.exists())
        write_json(self.root / 'integration-result.json', {'status':'PASS', 'kind':'ENGINEERING_NATIVE_NOT_T09_MODEL',
                   'commands_executed':count, 'recovery_dispatched_commands':0, 'resource_result':result})
        return json.loads((observation / 'reports/summary.json').read_text())

    def test_python_protected_report_cleanup_and_recovery(self):
        guard = self.root / 'producer-guard'
        guard.mkdir()
        code = ('from pathlib import Path\nimport errno, sys\n'
                'try: Path(sys.argv[1]).read_bytes()\n'
                'except OSError as e: assert e.errno in (errno.EPERM, errno.EACCES), repr(e)\n'
                'else: raise AssertionError("private expectation unexpectedly readable")\n')
        self.native([self.helper,'-I','-B','-c',code,self.protected / 'expected.json'],
                    guard,[self.public,self.project],[guard],'producer-private-boundary')
        self.python_producer()
        # The product-side public fixture can no longer execute. Protected copy
        # must still work; this demonstrates the loaded source, not only hashes.
        (self.public / 'python/python_probe.py').write_text('raise RuntimeError("product-side helper must not load")\n')
        result = self.verification()
        self.assertTrue(result['loaded']['python']['helper'].startswith(str(self.protected)))
        self.assertEqual(result['loaded']['python']['observation']['calculation'], self.calculation)

    def test_python_delivery_new_directory_new_input_and_environment(self):
        delivery = self.root / '交付目录 with spaces'
        shutil.copytree(self.public / 'python', delivery / 'python')
        self.public = delivery
        self.project = delivery / 'project'
        self.project.mkdir()
        (self.project / 'local_values.py').write_text('VALUE = 91\n')
        self.python = self.new_venv('交付 clean venv')
        self.reads = [path for path in self.reads if path != self.root / 'project venv']
        self.reads.append(self.python.parent.parent)
        profile = self.py.bind(str(self.python), [str(self.project)], [str(self.project / 'local_values.py')])
        self.input = delivery / 'new-input.json'
        write_json(self.input, {'schema_version':'1', 'modules':['local_values'],
                               'decimal_values':['1.25','-0.05'], 'sqlite_values':[8,-2,7]})
        profile = self.observe_python(profile, 'host-delivery-python-observation')
        write_json(delivery / 'python/profile.json', profile)
        write_json(self.protected / 'python/profile.json', profile)
        self.calculation = {'decimal_sum':'1.20','sqlite_count':3,'sqlite_sum':13}
        self.expectation()
        self.python_producer('delivery')
        result = self.verification()
        self.assertEqual(result['loaded']['python']['observation']['python']['prefix'], str(self.python.parent.parent))
        # No granted read includes developer code or the discarded first public
        # directory: only copied deliveries, protected checks and declared tools.
        for command in self.commands:
            filesystem = command['permission_profile']['filesystem']
            self.assertNotIn(str(ROOT), filesystem)
            self.assertNotIn(str(PACKAGES), filesystem)

    def test_native_timed_out_stack_command_stops_owned_child_and_keeps_capture(self):
        work = self.root / 'timeout-work'
        work.mkdir()
        script = self.project / 'owned_children.py'
        script.write_text('import subprocess, sys, time\nfrom pathlib import Path\n'
                          'child = subprocess.Popen(["/bin/sleep", "30"])\n'
                          'Path(sys.argv[1]).write_text(str(child.pid))\n'
                          'time.sleep(30)\n')
        report = work / 'capture'
        raw = self.native([self.helper,'-I','-B',self.public / 'python/python_environment.py','run',
            '--profile',self.public / 'python/profile.json','--cwd',work,'--report-dir',report,
            '--timeout','0.3','--script',script,'--',work / 'grandchild.pid'],
            work,[self.public,self.project],[work],'timeout',{'TMPDIR':str(work)}, expected_status='VALIDATION_FAILED')
        capture = json.loads((report / 'invocation.json').read_text())
        self.assertEqual(capture['status'], 'TIMEOUT')
        self.assertTrue(capture['complete'])
        self.assertNotEqual(raw['status'], 'PASS')
        child_pid = int((work / 'grandchild.pid').read_text())
        deadline = time.monotonic() + 3
        while True:
            state = subprocess.run(['/bin/ps','-o','stat=','-p',str(child_pid)],
                                   capture_output=True,text=True,check=False).stdout.strip()
            if not state or state.startswith('Z'):
                break
            self.assertLess(time.monotonic(), deadline, 'owned grandchild is still running: ' + state)
            time.sleep(0.05)
        before = digests(report)
        recovered = self.py.runtime.read_capture(report)
        self.assertEqual(recovered['status'], 'TIMEOUT')
        self.assertEqual(digests(report), before)
        self.assertEqual(len(self.commands), 1)
        write_json(self.root / 'integration-result.json', {'status':'PASS', 'kind':'ENGINEERING_NATIVE_TIMEOUT',
                   'business_status':'TIMEOUT_NOT_PASS', 'owned_child_running':False,
                   'commands_executed':1, 'recovery_dispatched_commands':0})

    def test_native_probe_reuse_for_new_inputs_and_changed_module(self):
        work = self.root / 'reuse-work'
        work.mkdir()
        script = self.project / 'business.py'
        script.write_text('import json, sys\nfrom decimal import Decimal\nfrom pathlib import Path\n'
                          'values=json.loads(Path(sys.argv[1]).read_text())\n'
                          'Path(sys.argv[2]).write_text(str(sum(map(Decimal, values), Decimal(0))))\n')
        receiver = self.root / 'reuse-receiver.json'
        write_json(receiver, {})
        roots = [self.protected, self.project, self.input, receiver]
        shape = LocalCommand.prepare(argv=[str(self.helper), '-I', '-B', '-c', 'pass'], cwd=work,
            read_roots=[*self.reads, *roots], write_roots=[work], network={'mode':'NONE'}, timeout_seconds=300)
        expected_receiver = {'receiver':'CODEX_SANDBOX_PERMISSION_PROFILE',
                             'permission_profile':shape.permission_profile(), 'network':{'mode':'NONE'}}
        write_json(receiver, expected_receiver)
        result = self.native([self.helper,'-I','-B',self.protected / 'python/check_python.py',
            '--profile',self.protected / 'python/profile.json','--input',self.input,
            '--expected',self.protected / 'python/expected.json','--cwd',work,
            '--report-dir',work / 'probe','--receiver',receiver], work, roots, [work], 'reuse-initial',
            {'FOUNDRY_VERIFIER_ROOT':str(self.protected)})
        report = json.loads(result['stdout'])
        self.assertEqual(report['status'], 'PASS')
        self.assertTrue(report['observations_complete'])
        before = digests(work / 'probe')
        decisions = []
        for index, (values, wanted) in enumerate([(['1.20','0.03'],'1.23'), (['-2','0.75'],'-1.25')], 1):
            input_path, output_path = work / f'input-{index}.json', work / f'output-{index}.txt'
            write_json(input_path, values)
            decision_start = time.monotonic()
            decision = self.py.runtime.reuse_probe(self.py_profile, report, expected_receiver)
            decision['elapsed_seconds'] = time.monotonic() - decision_start
            decisions.append(decision)
            self.assertEqual(decision['decision'], 'REUSE')
            self.native([self.helper,'-I','-B',self.protected / 'python/python_environment.py','run',
                '--profile',self.protected / 'python/profile.json','--cwd',work,
                '--report-dir',work / f'business-{index}','--script',script,'--',input_path,output_path],
                work, roots, [work], f'reuse-business-{index}')
            self.assertEqual(output_path.read_text(), wanted)
        self.assertEqual(digests(work / 'probe'), before)
        self.assertEqual(len(self.commands), 3)
        self.assertEqual([c['permission_profile'] for c in self.commands], [shape.permission_profile()] * 3)
        shutil.copyfile(self.project / 'local_values.py', self.root / 'local_values-before-change.py')
        (self.project / 'local_values.py').write_text('VALUE = 24\n')
        changed = self.py.runtime.reuse_probe(self.py_profile, report, expected_receiver)
        self.assertEqual(changed['decision'], 'REPROBE')
        self.assertEqual(len(self.commands), 3)
        write_json(self.root / 'integration-result.json', {'status':'PASS', 'kind':'ENGINEERING_NATIVE_REUSE',
            'diagnostic_commands':1, 'new_input_business_commands':2, 'recovery_dispatched_commands':0,
            'new_input_decisions':decisions, 'module_change_decision':changed,
            'human_configuration_interventions_after_binding':0,
            'command_elapsed_seconds':[r['elapsed_seconds'] for r in self.commands]})

    @unittest.skipUnless(os.environ.get('HFFACTORY_STACK_CMAKE') and os.environ.get('HFFACTORY_STACK_QT_SDK'),
                         'selected real Kitware/Qt paths required')
    def test_real_preset_and_profile_environment_priority(self):
        qt, profile = self.prepare_qt()
        profile['environment']['set']['FOUNDRY_STACK_MARKER'] = 'profile'
        write_json(self.public / 'qt/profile.json', profile)
        source = self.project / 'preset source'
        source.mkdir()
        (source / 'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.21)\n'
            'project(preset_priority LANGUAGES CXX)\nfind_package(Qt6 REQUIRED COMPONENTS Core)\n'
            'file(WRITE "${CMAKE_BINARY_DIR}/observed.txt" "${CHOICE}\\n$ENV{FOUNDRY_STACK_MARKER}\\n${Qt6_DIR}\\n")\n'
            'add_custom_target(marker ALL COMMAND "${CMAKE_COMMAND}" -P "${CMAKE_SOURCE_DIR}/marker.cmake")\n'
            'enable_testing()\nadd_test(NAME marker COMMAND "${CMAKE_COMMAND}" -P "${CMAKE_SOURCE_DIR}/marker.cmake")\n')
        (source / 'marker.cmake').write_text('message("STACK_MARKER=$ENV{FOUNDRY_STACK_MARKER}")\n'
            'if(NOT "$ENV{FOUNDRY_STACK_MARKER}" STREQUAL "profile")\nmessage(FATAL_ERROR "incorrect stage environment")\nendif()\n')
        write_json(source / 'CMakePresets.json', {'version':3,'configurePresets':[{'name':'selected',
            'generator':'Unix Makefiles','environment':{'FOUNDRY_STACK_MARKER':'preset'},
            'cacheVariables':{'Qt6_DIR':'/invalid-preset-sdk','CHOICE':'preset'}}]})
        work = self.root / 'preset-work'
        work.mkdir()
        for step in ('configure','build','test'):
            argv = [self.helper,'-I','-B',self.public / 'qt/qt_cmake.py',step,'--profile',self.public / 'qt/profile.json',
                    '--build-dir',work / 'build','--report-dir',work / 'reports' / step]
            if step == 'configure': argv += ['--source',source,'--preset','selected','--define','CHOICE=cli']
            self.native(argv,work,[self.public,self.project],[work],'preset-' + step,
                        {'TMPDIR':str(work),'FOUNDRY_STACK_MARKER':'outer'})
        observed = (work / 'build/observed.txt').read_text().splitlines()
        self.assertEqual(observed, ['cli','preset',profile['extensions']['qt']['cmake_dir']])
        self.assertIn('STACK_MARKER=profile', (work / 'reports/build/stderr.txt').read_text())
        self.assertIn('STACK_MARKER=profile', (work / 'reports/test/junit.xml').read_text())
        write_json(self.root / 'integration-result.json', {'status':'PASS','kind':'ENGINEERING_NATIVE_PRESET',
            'actual_configure_values':observed,'build_and_test_marker':'profile','commands_executed':3})

    @unittest.skipUnless(os.environ.get('HFFACTORY_STACK_CMAKE') and os.environ.get('HFFACTORY_STACK_QT_SDK'),
                         'selected real Kitware/Qt paths required')
    def test_real_zero_tests_and_fake_ctest_success_are_not_probe_pass(self):
        self.prepare_qt()
        for variant in ('zero-tests','fake-success'):
            public = self.root / variant / 'qt'
            shutil.copytree(self.public / 'qt', public)
            cmake = public / 'probe-CMakeLists.txt'
            original = cmake.read_text()
            if variant == 'zero-tests':
                cmake.write_text(original.split('enable_testing()')[0])
            else:
                cmake.write_text(original.split('enable_testing()')[0] +
                    'enable_testing()\nadd_test(NAME qt-environment-probe COMMAND /usr/bin/true)\n')
                (public / 'probe-main.cpp').write_text('#include <QtCore/QTextStream>\n'
                    'int main() { QTextStream(stdout) << "QtCore:4" << Qt::endl; return 0; }\n')
            work = self.root / (variant + '-work')
            work.mkdir()
            self.native([self.helper,'-I','-B',public / 'qt_environment.py','probe','--profile',public / 'profile.json',
                '--work-dir',work / 'work','--report-dir',work / 'report','--receiver','CODEX_SANDBOX_PERMISSION_PROFILE'],
                work,[public],[work],variant,{'TMPDIR':str(work)},expected_status='VALIDATION_FAILED')
            result = json.loads((work / 'report/probe.json').read_text())
            self.assertEqual(result['status'], 'ERROR')
            if variant == 'zero-tests':
                self.assertIn('probe test failed', str(result['issues']))
                self.assertFalse((work / 'report/run').exists())
            else:
                self.assertTrue(all(row['record']['returncode'] == 0 for row in result['operations']))
                self.assertIn('unexpected actual QtCore output: QtCore:4', result['issues'])
        write_json(self.root / 'integration-result.json', {'status':'PASS','kind':'ENGINEERING_NATIVE_FALSE_SUCCESS_REJECTION',
            'zero_tests':'ERROR','all_commands_zero_wrong_actual_output':'ERROR','commands_executed':2})

    @unittest.skipUnless(os.environ.get('HFFACTORY_STACK_CMAKE') and os.environ.get('HFFACTORY_STACK_QT_SDK')
                         and os.environ.get('HFFACTORY_STACK_OUTSIDE_LIBRARY'),
                         'selected Qt and an ordinary undeclared control library are required')
    def test_selected_alias_read_proposals_enable_native_reobservation_and_keep_other_kegs_denied(self):
        qt, qt_profile = self.prepare_qt()
        profiles = {'python': self.py_profile, 'qt': qt_profile}
        aliases = {}
        for name, profile in profiles.items():
            observed_aliases = profile['extensions'].get('path_aliases', [])
            self.assertTrue(observed_aliases, 'selected host observation must bind actual path aliases')
            self.assertTrue(all(row['status'] == 'OBSERVED' for row in observed_aliases))
            declared = set(map(str, map(Path, profile['read_paths'])))
            for row in observed_aliases:
                self.assertIn(row['read_parent'], declared,
                              'lookup parent must be an explicit proposal, not an implicit native grant')
                aliases[row['path']] = row
        self.assertTrue(any(Path(row['path']).parent == Path('/opt/homebrew/opt')
                            for row in aliases.values()), 'this case covers the actual Homebrew opt failure')
        outside_alias = Path(os.environ['HFFACTORY_STACK_OUTSIDE_LIBRARY'])
        outside_real = outside_alias.resolve(strict=True)
        self.assertTrue(outside_real.is_file())
        self.assertFalse(any(outside_real == root.resolve() or outside_real.is_relative_to(root.resolve())
                             for root in self.reads), 'control library must remain outside the selected real reads')
        work = self.root / 'native-reobservation-work'
        work.mkdir()
        common_reads = [self.public, self.project, self.input]
        python_profile, new_qt_profile = work / 'python-profile.json', work / 'qt-profile.json'
        self.native([self.helper, '-I', '-B', self.public / 'python/python_environment.py', 'observe-native',
            '--profile', self.public / 'python/profile.json', '--input', self.input,
            '--otool', '/usr/bin/otool', '--report-dir', work / 'python-observe',
            '--adapt-loader-paths', '--output', python_profile], work, common_reads, [work],
            'native-python-reobserve', {'TMPDIR': str(work)})
        self.native([self.helper, '-I', '-B', self.public / 'qt/qt_environment.py', 'observe',
            '--profile', self.public / 'qt/profile.json', '--report-dir', work / 'qt-observe',
            '--adapt-loader-paths', '--output-profile', new_qt_profile], work, common_reads, [work],
            'native-qt-reobserve', {'TMPDIR': str(work)})
        actual_profiles = {'python': json.loads(python_profile.read_text()),
                           'qt': json.loads(new_qt_profile.read_text())}
        for name, profile in actual_profiles.items():
            self.assertEqual(profile['tools'], profiles[name]['tools'])
            self.assertEqual(profile['environment'], profiles[name]['environment'])
            self.assertEqual(sorted(profile['observations'], key=lambda row: row['path']),
                             sorted(profiles[name]['observations'], key=lambda row: row['path']))
            self.assertEqual(sorted(profile['extensions']['path_aliases'], key=lambda row: row['path']),
                             sorted(profiles[name]['extensions']['path_aliases'], key=lambda row: row['path']))
        self.native([self.helper, '-I', '-B', self.public / 'python/python_environment.py', 'probe',
            '--profile', python_profile, '--input', self.input, '--cwd', work,
            '--report-dir', work / 'python-probe'], work, common_reads, [work],
            'native-python-reobserved-probe', {'TMPDIR': str(work)})
        self.native([self.helper, '-I', '-B', self.public / 'qt/qt_environment.py', 'probe',
            '--profile', new_qt_profile, '--work-dir', work / 'qt-work', '--report-dir', work / 'qt-probe',
            '--receiver', 'CODEX_SANDBOX_PERMISSION_PROFILE'], work, common_reads, [work],
            'native-qt-reobserved-probe', {'TMPDIR': str(work)})
        self.assertEqual(json.loads((work / 'python-probe/observation.json').read_text())['calculation'], self.calculation)
        self.assertEqual((work / 'qt-probe/run/stdout.txt').read_text().strip(), 'QtCore:3')
        selected_aliases = list(aliases)
        boundary_code = ('import errno,json,sys\nfrom pathlib import Path\n'
            'selected=json.loads(sys.argv[1]); denied=[]\n'
            'for value in selected: Path(value).resolve(strict=True)\n'
            'for value in sys.argv[2:]:\n'
            ' try:\n'
            '  with Path(value).open("rb") as stream: stream.read(1)\n'
            ' except OSError as error:\n'
            '  assert error.errno in (errno.EPERM,errno.EACCES), repr(error)\n'
            '  denied.append(value)\n'
            ' else: raise AssertionError("undeclared library became readable: "+value)\n'
            'print(json.dumps({"selected_aliases_resolved":len(selected),"denied":denied,"content_output":False}))\n')
        self.native([self.helper, '-I', '-B', '-c', boundary_code, json.dumps(selected_aliases),
                     outside_alias, outside_real], work, common_reads, [work], 'native-lookup-read-boundary',
                    {'TMPDIR': str(work)})
        self.assertTrue(all(command['permission_profile'] == self.commands[0]['permission_profile']
                            for command in self.commands), 'reobservation and real probes use the same declared scope')
        before, count = digests(work), len(self.commands)
        recovered_python = self.py.runtime.read_capture(work / 'python-probe')
        recovered_qt = qt.inspect_probe(actual_profiles['qt'], work / 'qt-probe',
                                        receiver='CODEX_SANDBOX_PERMISSION_PROFILE')
        reusable = qt.runtime.reuse_probe(actual_profiles['qt'],
            json.loads((work / 'qt-probe/probe.json').read_text()), 'CODEX_SANDBOX_PERMISSION_PROFILE')
        self.assertEqual(recovered_python['returncode'], 0)
        self.assertEqual(recovered_qt['status'], 'PASS')
        self.assertEqual(reusable['decision'], 'REUSE')
        self.assertEqual(digests(work), before)
        self.assertEqual(len(self.commands), count)
        for invocation in work.rglob('invocation.json'):
            captured = json.loads(invocation.read_text())
            if captured.get('pid'):
                with self.assertRaises(ProcessLookupError):
                    os.killpg(captured['pid'], 0)
        write_json(self.root / 'integration-result.json', {'status': 'PASS',
            'kind': 'ENGINEERING_NATIVE_REOBSERVATION_NOT_T09_MODEL',
            'actual_receiver_commands': count, 'models': 0, 'T09_attempts': 0,
            'native_selected_aliases': selected_aliases, 'outside_library': str(outside_real),
            'outside_alias_and_real_read_denied': True, 'read_root_boundary':
            'Selected lookup-parent directories expose their names and link metadata; this is broader than exact alias permission, while the ordinary unselected keg is unreadable.',
            'recovery_dispatched_commands': 0, 'reports_unchanged_after_retrieval': True,
            'qt_diagnostic_reuse': reusable})

    def prepare_qt(self):
        qt = module(PACKAGES / 'qt-cmake/2/qt_environment.py', 'native_qt_env')
        cmake = Path(os.environ['HFFACTORY_STACK_CMAKE'])
        sdk = Path(os.environ['HFFACTORY_STACK_QT_SDK'])
        tools = {'qt-python':str(self.helper), 'cmake':str(cmake), 'ctest':str(cmake.with_name('ctest')),
                 'otool':'/usr/bin/otool'}
        profile = qt.discover(tools, [str(sdk)], environment={'set':{
            'PATH':'/usr/bin:/bin:/usr/sbin:/sbin',
            'CC':'/Library/Developer/CommandLineTools/usr/bin/clang',
            'CXX':'/Library/Developer/CommandLineTools/usr/bin/clang++',
            'SDKROOT':os.environ.get('HFFACTORY_STACK_MACOS_SDK','/Library/Developer/CommandLineTools/SDKs/MacOSX.sdk')},
            'prepend':{}})['profile']
        observed = qt.observe(profile, self.root / 'host-selected-tool-observation', adapt_loader_paths=True)
        self.assertEqual(observed['status'], 'OBSERVED', observed)
        profile = observed['profile']
        self.reads += [cmake.parent.parent, sdk, Path('/Library/Developer/CommandLineTools'),
                       *map(Path, profile['read_paths']), *[Path(v['path']).parent for v in profile['observations']]]
        for target in (self.public / 'qt', self.protected / 'qt'):
            shutil.copytree(PACKAGES / 'qt-cmake/2', target,
                            ignore=shutil.ignore_patterns('check_ctest.py') if target.parent == self.public else None)
            write_json(target / 'profile.json', profile)
        self.assertEqual((self.public / 'qt/profile.json').read_bytes(), (self.protected / 'qt/profile.json').read_bytes())
        return qt, profile

    @unittest.skipUnless(os.environ.get('HFFACTORY_STACK_CMAKE') and os.environ.get('HFFACTORY_STACK_QT_SDK'),
                         'selected real Kitware/Qt paths required')
    def test_qt_python_composed_receiver_and_protected_resource_lifecycle(self):
        qt, profile = self.prepare_qt()
        work = self.root / 'producer-qt-work'
        work.mkdir()
        self.native([self.helper, '-I','-B',self.public / 'qt/qt_environment.py','probe',
            '--profile',self.public / 'qt/profile.json','--work-dir',work / 'work','--report-dir',work / 'reports',
            '--receiver','CODEX_SANDBOX_PERMISSION_PROFILE'], work, [self.public], [work], 'qt-producer',
            {'TMPDIR':str(work)})
        self.python_producer()
        (self.public / 'qt/qt_environment.py').write_text('raise RuntimeError("product-side Qt helper must not load")\n')
        (self.public / 'python/python_probe.py').write_text('raise RuntimeError("product-side Python helper must not load")\n')
        result = self.verification(qt=True)
        self.assertTrue(result['loaded']['qt']['helper'].startswith(str(self.protected)))
        self.assertEqual(len(result['checks']), 3)


if __name__ == '__main__':
    unittest.main()
