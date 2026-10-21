"""Protected project-parameterized checker: run CTest once, inspect its JUnit.

The caller protects this file and its project expectation, binds the build to
the checked product and owns resource permissions, timeouts and acceptance.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


def validate_required(required):
    if (not isinstance(required, list) or not required
            or not all(isinstance(name, str) and name for name in required)
            or len(set(required)) != len(required)):
        raise ValueError('independent expectation requires unique nonempty required_tests')
    return required


def read_expected(path):
    document = json.loads(Path(path).read_text(encoding='utf-8'))
    return validate_required(document.get('required_tests') if isinstance(document, dict) else None)


def inspect_report(junit_path, record, required):
    """Read retained evidence only; this API never launches or grants acceptance."""
    result = {'status': 'ERROR', 'checked_tests': [], 'issues': []}
    try:
        validate_required(required)
    except ValueError as error:
        result['issues'].append(str(error))
        return result
    if record.get('status') != 'FINISHED' or not isinstance(record.get('returncode'), int):
        result['issues'].append('CTest did not finish with a recorded return code')
        return result
    try:
        root = ET.parse(junit_path).getroot()
    except (OSError, ET.ParseError) as error:
        result['issues'].append('JUnit unavailable: ' + str(error))
        return result
    if root.tag not in ('testsuite', 'testsuites'):
        result['issues'].append('not a JUnit testsuite document')
        return result
    cases = list(root.iter('testcase'))
    names = [case.get('name') for case in cases]
    result['checked_tests'] = names
    if not cases or any(not name for name in names) or len(set(names)) != len(names):
        result['issues'].append('no tests, unnamed tests or ambiguous duplicate test names')
        return result
    execution_errors, failures = [], []
    for case in cases:
        status = case.get('status', '').lower()
        if (case.find('error') is not None or case.find('skipped') is not None
                or status in ('notrun', 'not_run', 'skipped', 'disabled')):
            execution_errors.append(case.get('name'))
        elif case.find('failure') is not None or status in ('fail', 'failed'):
            failures.append(case.get('name'))
    # CTest and ordinary JUnit can report suite errors not attached to a case.
    for suite in root.iter('testsuite'):
        try:
            if int(suite.get('errors', '0')) > 0:
                execution_errors.append('suite errors')
            if int(suite.get('failures', '0')) > 0 and not failures:
                failures.append('suite failures')
            if any(int(suite.get(field, '0')) > 0 for field in ('skipped', 'disabled')):
                execution_errors.append('suite skipped/disabled tests')
        except ValueError:
            execution_errors.append('invalid suite counters')
    missing = sorted(set(required) - set(names))
    if record['returncode'] < 0:
        execution_errors.append('CTest terminated by signal')
    elif record['returncode'] not in (0, 8) or record['returncode'] == 8 and not failures:
        execution_errors.append('CTest did not finish with a normal test result')
    if execution_errors:
        result['issues'].append({'execution_errors': execution_errors})
    if failures:
        result['issues'].append({'failed_tests': failures})
    if missing:
        result['issues'].append({'missing_required_tests': missing})
    result['status'] = 'ERROR' if execution_errors else 'ASSERTION' if failures or missing else 'PASS'
    return result


def structured_report(result, check_id, case_id, command_id):
    """Map one project-declared obligation to the existing STRUCTURED_V1."""
    if not all(isinstance(value, str) and value.strip() for value in (check_id, case_id, command_id)):
        raise ValueError('structured report needs the declared check ID and actual host identities')
    status = result['status']
    report = {'schema_version': '1.0', 'case_id': case_id, 'command_id': command_id,
              'status': 'CHECKS_PASS' if status == 'PASS' else 'CHECKS_FAILED',
              'checks': [{'id': check_id, 'status': {'PASS': 'PASS', 'ASSERTION': 'FAIL', 'ERROR': 'ERROR'}[status]}],
              'errors': result.get('issues', []) if status == 'ERROR' else [],
              'ctest_diagnostics': result}
    if status == 'ASSERTION':
        report['failure_kind'] = 'ASSERTION'
    return report


def check(arguments):
    protected = os.environ.get('FOUNDRY_VERIFIER_ROOT')
    if protected:
        verifier = Path(protected).resolve(strict=True)
        if (not verifier.is_dir() or not Path(__file__).resolve().is_relative_to(verifier)
                or not Path(arguments.expected).resolve().is_relative_to(verifier)):
            raise ValueError('checker and independent expectation must use the protected verifier copy')
    required = read_expected(arguments.expected)
    tool = Path(arguments.ctest)
    if not tool.is_absolute() or not tool.is_file() or not os.access(tool, os.X_OK):
        raise ValueError('supply an existing absolute CTest executable path')
    build = Path(arguments.build_dir).resolve(strict=True)
    if not build.is_dir():
        raise ValueError('build must be a directory')
    report = Path(arguments.report_dir).resolve()
    report.mkdir(parents=True, exist_ok=False)
    junit = report / 'junit.xml'
    argv = [str(tool), '--test-dir', str(build), '--output-on-failure',
            '--no-tests=error', '--output-junit', str(junit)]
    if arguments.config:
        argv.extend(['-C', arguments.config])
    if arguments.test_regex:
        argv.extend(['-R', arguments.test_regex])
    record = {'schema_version': '1', 'command': 'test', 'status': 'STARTED', 'argv': argv,
              'cwd': str(build), 'build_dir': str(build), 'report_dir': str(report)}
    record_path = report / 'invocation.json'
    record_path.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    try:
        with (report / 'stdout.log').open('wb') as stdout, (report / 'stderr.log').open('wb') as stderr:
            completed = subprocess.run(argv, cwd=build, stdout=stdout, stderr=stderr, check=False)
        record.update(status='FINISHED', returncode=completed.returncode)
    except OSError as error:
        record.update(status='ERROR', error_type=type(error).__name__, error=str(error))
    record_path.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    result = inspect_report(junit, record, required)
    (report / 'check-result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('ctest', 'build-dir', 'report-dir', 'expected'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--config')
    parser.add_argument('--test-regex')
    parser.add_argument('--foundry-check-id', help='emit the existing resource summary for this declared obligation')
    arguments = parser.parse_args(argv)
    context = None
    try:
        if arguments.foundry_check_id is not None:
            case_id, command_id = (os.environ.get(name) for name in ('FOUNDRY_CASE_ID', 'FOUNDRY_COMMAND_ID'))
            structured_report({'status': 'PASS'}, arguments.foundry_check_id, case_id, command_id)
            directory = os.environ.get('FOUNDRY_REPORT_DIR')
            if not directory or not Path(directory).is_dir():
                raise ValueError('FOUNDRY_REPORT_DIR must be the existing host report directory')
            summary = Path(directory) / 'summary.json'
            if summary.exists() or summary.is_symlink():
                raise ValueError('summary.json already exists; read retained evidence instead of replaying')
            context = (summary, case_id, command_id)
        result = check(arguments)
    except (OSError, ValueError) as error:
        result = {'status': 'ERROR', 'issues': [str(error)]}
    if context is not None:
        summary, case_id, command_id = context
        try:
            with summary.open('x', encoding='utf-8') as output:
                json.dump(structured_report(result, arguments.foundry_check_id, case_id, command_id), output, indent=2)
                output.write('\n')
        except (OSError, ValueError) as error:
            result = {'status': 'ERROR', 'issues': ['structured report unavailable: ' + str(error)]}
    print(json.dumps(result))
    return {'PASS': 0, 'ASSERTION': 1, 'ERROR': 2}[result['status']]


if __name__ == '__main__':
    raise SystemExit(main())
