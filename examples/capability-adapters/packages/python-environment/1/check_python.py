"""Protected Python environment probe and independent project expectation check.

The default executes the protected public fixture once. --recover reads only an
existing checker-owned capture; it never replays an import or a project command.
"""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path


_spec = importlib.util.spec_from_file_location('protected_python_stack_runtime', Path(__file__).with_name('stack_runtime.py'))
runtime = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runtime)
PACKAGE = {'name': 'python-environment', 'version': '1'}
BASE_MODULES = {'decimal', '_decimal', 'sqlite3', '_sqlite3'}


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def call_path(value):
    path = Path(value)
    return str(path.parent.resolve() / path.name)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expected_document(path):
    expected = read_json(path)
    if not isinstance(expected, dict) or expected.get('schema_version') != '1':
        raise ValueError('independent expectation requires schema_version 1')
    python = expected.get('python')
    if (not isinstance(python, dict) or not isinstance(python.get('prefix'), str)
            or not Path(python['prefix']).is_absolute() or type(python.get('require_venv')) is not bool):
        raise ValueError('independent expectation requires absolute python.prefix and require_venv')
    version = python.get('version_min')
    if (not isinstance(version, list) or not 2 <= len(version) <= 3
            or any(type(value) is not int or value < 0 for value in version)):
        raise ValueError('python.version_min requires two or three integers')
    modules = expected.get('modules')
    if not isinstance(modules, dict):
        raise ValueError('independent module source expectations must be an object')
    for name, rule in modules.items():
        if not isinstance(name, str) or not isinstance(rule, dict) or set(rule) - {'origin', 'origin_root', 'sha256'}:
            raise ValueError('module source rule supports origin, origin_root and sha256')
        if any(not isinstance(value, str) for value in rule.values()):
            raise ValueError('module source expectations must be strings')
    calculation = expected.get('calculation')
    if (not isinstance(calculation, dict) or set(calculation) != {'decimal_sum', 'sqlite_count', 'sqlite_sum'}
            or not isinstance(calculation['decimal_sum'], str)
            or type(calculation['sqlite_count']) is not int or type(calculation['sqlite_sum']) is not int):
        raise ValueError('independent calculation requires decimal_sum, sqlite_count and sqlite_sum')
    return expected


def inspect_capture(report_dir, profile, input_path, expected):
    """Read a previously trusted checker capture; no subprocess and no acceptance grant."""
    result = {'status': 'ERROR', 'issues': [], 'observation': None}
    try:
        report_dir = Path(report_dir)
        record = runtime.read_capture(report_dir)
        if record.get('status') != 'FINISHED' or type(record.get('returncode')) is not int:
            raise ValueError('probe has no complete command result; preserve unknown outcome without replay')
        metadata = record.get('metadata', {})
        if (metadata.get('operation') != 'probe' or metadata.get('profile_sha256') != runtime.profile_digest(profile)
                or metadata.get('input_sha256') != digest(input_path)):
            raise ValueError('capture differs from the supplied profile or probe input')
        specification = read_json(input_path)
        observed = read_json(report_dir / 'observation.json')
        result['observation'] = observed
        if observed.get('input_sha256') != digest(input_path):
            raise ValueError('observation is not bound to the probe input')
        if observed.get('status') != 'OBSERVED' or record['returncode'] != 0:
            result['issues'].append({'environment_errors': observed.get('errors', []), 'returncode': record['returncode']})
            return result
        modules = observed.get('modules')
        requested = BASE_MODULES | set(specification['modules'])
        if not isinstance(modules, dict) or set(modules) != requested:
            raise ValueError('incomplete or extra module observations')
        if set(expected['modules']) - requested:
            raise ValueError('expected module was not requested by the public probe input')
        for name, facts in modules.items():
            if facts.get('imported') is not True:
                raise ValueError('module was not actually imported: ' + name)
            if name in {'_decimal', '_sqlite3'} and facts.get('native_extension') is not True:
                raise ValueError('standard native extension was not loaded: ' + name)
            file = facts.get('file')
            if file and (digest(file['path']) != file['sha256'] or str(Path(file['path']).resolve()) != file['resolved_path']):
                raise ValueError('module source changed after capture: ' + name)
        python = observed['python']
        actual_call = call_path(python['executable'])
        if actual_call != call_path(runtime.tool(profile, 'project-python')):
            raise ValueError('probe used a different interpreter invocation')
        if not python.get('isolated') or python.get('no_site'):
            raise ValueError('probe must keep isolated mode and the selected venv site-packages')
        expected_paths = profile.get('extensions', {}).get('python', {}).get('project_paths', [])
        if observed.get('project_paths') != expected_paths:
            raise ValueError('probe used different explicit project paths')
        # These comparisons consume independent project expectations. They do
        # not import the probe or recompute its algorithm.
        failures = []
        if Path(python['prefix']).resolve() != Path(expected['python']['prefix']).resolve():
            failures.append('interpreter prefix differs from independent expectation')
        if expected['python']['require_venv'] and Path(python['prefix']).resolve() == Path(python['base_prefix']).resolve():
            failures.append('selected interpreter is not the required venv')
        minimum = expected['python']['version_min']
        if tuple(python['version_info'][:len(minimum)]) < tuple(minimum):
            failures.append('interpreter version is below the declared project minimum')
        for name, rule in expected['modules'].items():
            origin = modules[name].get('origin')
            if 'origin' in rule and origin != rule['origin']:
                failures.append('module origin differs: ' + name)
            if 'origin_root' in rule and (not origin or origin in {'built-in', 'frozen'}
                    or not Path(origin).resolve().is_relative_to(Path(rule['origin_root']).resolve())):
                failures.append('module is outside expected source root: ' + name)
            if 'sha256' in rule and (modules[name].get('file') or {}).get('sha256') != rule['sha256']:
                failures.append('module source digest differs: ' + name)
        if json.dumps(observed.get('calculation'), sort_keys=True) != json.dumps(expected['calculation'], sort_keys=True):
            failures.append('native calculation differs from independent expectation')
        result.update(status='ASSERTION' if failures else 'PASS', issues=failures)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as error:
        result['issues'].append(str(error))
    return result


def check(args):
    here = Path(__file__).resolve().parent
    protected = os.environ.get('FOUNDRY_VERIFIER_ROOT')
    if protected:
        root = Path(protected).resolve(strict=True)
        for path in (Path(__file__), here / 'python_probe.py', here / 'stack_runtime.py', Path(args.profile), Path(args.expected)):
            if not path.resolve(strict=True).is_relative_to(root):
                raise ValueError('checker, public dependencies, profile and expectation must use protected copies')
    profile = runtime.load_profile(args.profile, PACKAGE)
    if 'probe' not in profile['operations']:
        raise ValueError('probe operation is not declared by this profile')
    expected = expected_document(args.expected)
    for old in profile['observations']:
        if old.get('status') != 'OBSERVED' or runtime.file_observation(old['path']) != old:
            raise ValueError('declared environment file changed or is unavailable; prepare a new profile: ' + old['path'])
    if not args.recover:
        input_path = Path(args.input).resolve(strict=True)
        report_dir = Path(args.report_dir).resolve()
        argv = [runtime.tool(profile, 'project-python'), '-I', '-B', str(here / 'python_probe.py'),
                '--input', str(input_path), '--output', str(report_dir / 'observation.json')]
        for path in profile.get('extensions', {}).get('python', {}).get('project_paths', []):
            argv.extend(['--project-path', path])
        runtime.run_capture(argv, args.cwd, report_dir, env=runtime.child_environment(profile), timeout=args.timeout,
            metadata={'package': PACKAGE, 'operation': 'probe', 'profile_sha256': runtime.profile_digest(profile),
                      'input_sha256': digest(input_path), 'checker': str(Path(__file__).resolve()),
                      'checker_files': {name: digest(here / name) for name in ('check_python.py', 'python_probe.py', 'stack_runtime.py')}})
    else:
        record = runtime.read_capture(args.report_dir)
        expected_files = {name: digest(here / name) for name in ('check_python.py', 'python_probe.py', 'stack_runtime.py')}
        if record.get('metadata', {}).get('checker_files') != expected_files:
            raise ValueError('recovery requires this checker version\'s existing capture, not producer observations')
    result = inspect_capture(args.report_dir, profile, args.input, expected)
    observations = []
    for facts in (result.get('observation') or {}).get('modules', {}).values():
        if facts.get('file'):
            observations.append(facts['file'])
        elif facts.get('origin') is None:
            # A namespace import may work, but directory contents are not a
            # concrete module-file identity. Leave its later reuse unconfirmed.
            observations.extend(runtime.file_observation(path) for path in facts.get('search_locations', []))
    native = profile.get('extensions', {}).get('python', {}).get('native_observation', {})
    loaded_native = {facts['file']['resolved_path'] for facts in (result.get('observation') or {}).get('modules', {}).values()
                     if facts.get('native_extension') and facts.get('file')}
    coverage = native.get('complete') is True and loaded_native.issubset(set(native.get('native_files', [])))
    result.update(complete=True, operation='probe', profile_sha256=runtime.profile_digest(profile),
                  receiver=read_json(args.receiver) if args.receiver else None, observations=observations,
                  observations_complete=coverage)
    return result


def structured(result, check_id):
    report = {'schema_version': '1.0', 'case_id': os.environ.get('FOUNDRY_CASE_ID', 'standalone'),
              'command_id': os.environ.get('FOUNDRY_COMMAND_ID', 'standalone'),
              'status': 'CHECKS_PASS' if result['status'] == 'PASS' else 'CHECKS_FAILED',
              'checks': [{'id': check_id, 'status': {'PASS': 'PASS', 'ASSERTION': 'FAIL', 'ERROR': 'ERROR'}[result['status']]}],
              'errors': result['issues'] if result['status'] == 'ERROR' else [], 'python_environment': result}
    if result['status'] == 'ASSERTION':
        report['failure_kind'] = 'ASSERTION'
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('profile', 'input', 'expected', 'cwd', 'report-dir'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--report')
    parser.add_argument('--foundry-check-id', default='python-environment')
    parser.add_argument('--recover', action='store_true')
    parser.add_argument('--receiver', help='host-declared receiver/permission JSON; omission leaves reuse unconfirmed')
    parser.add_argument('--timeout', type=float, default=900)
    args = parser.parse_args(argv)
    report = args.report
    if report is None and os.environ.get('FOUNDRY_REPORT_DIR'):
        report = str(Path(os.environ['FOUNDRY_REPORT_DIR']) / 'summary.json')
    try:
        # An existing summary is a recovery concern, never a reason to probe again.
        if report and (Path(report).exists() or Path(report).is_symlink()):
            raise ValueError('summary already exists; read retained evidence or choose a new summary for recovery')
        result = check(args)
    except (OSError, ValueError, TypeError) as error:
        result = {'status': 'ERROR', 'issues': [str(error)]}
    if report:
        try:
            runtime.write_new_json(report, structured(result, args.foundry_check_id))
        except (OSError, ValueError) as error:
            result = {'status': 'ERROR', 'issues': [str(error)]}
    print(json.dumps(result, ensure_ascii=False))
    return {'PASS': 0, 'ASSERTION': 1, 'ERROR': 2}[result['status']]


if __name__ == '__main__':
    raise SystemExit(main())
