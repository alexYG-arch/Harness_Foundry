"""Adapt DOC/API observations to existing STRUCTURED_V1 resource reports.

Only the controller accepts a Build. This entry reads its checker and independent
expectation from the protected verifier snapshot and never writes product files.
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import traceback


def validate_expected(kind, expected):
    """Check the protected input shape before attributing failures to a target."""
    def strings(values):
        return isinstance(values, list) and all(isinstance(value, str) for value in values)

    if kind == 'doc':
        valid = (isinstance(expected['title'], str) and isinstance(expected['user_notes'], str)
                 and all(strings(expected[key]) for key in ('ordered_headings', 'required_facts', 'citations', 'priorities'))
                 and isinstance(expected.get('source_titles', True), bool)
                 and isinstance(expected['section_lines'], dict)
                 and all(isinstance(key, str) and strings(value) for key, value in expected['section_lines'].items())
                 and isinstance(expected['sources'], dict)
                 and all(isinstance(key, str) and isinstance(value['title'], str) and isinstance(value['locator'], str)
                         for key, value in expected['sources'].items()))
    else:
        valid = (type(expected['timeout']) in (int, float) and isinstance(expected['items'], list)
                 and isinstance(expected['health'], dict) and isinstance(expected['not_found'], dict))
    if not valid:
        raise ValueError('protected expectation has an invalid contract shape')


def run_checks(kind, stage, target):
    report_dir = Path(os.environ['FOUNDRY_REPORT_DIR'])
    verifier = Path(os.environ['FOUNDRY_VERIFIER_ROOT']).resolve(strict=True)
    report = {'schema_version': '1.0', 'case_id': os.environ['FOUNDRY_CASE_ID'],
              'command_id': os.environ['FOUNDRY_COMMAND_ID'], 'status': 'CHECKS_FAILED',
              'checks': [], 'errors': []}
    state = {'services_stopped': False}
    check_id = 'document-content' if kind == 'doc' else 'api-contract'
    try:
        if Path(__file__).resolve().parent != verifier:
            raise RuntimeError('resource checker must run from its protected verifier root')
        spec = importlib.util.spec_from_file_location('protected_mechanism_checks', verifier/'check_mechanisms.py')
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        expected = checker.read_json(verifier/'expectations'/f'{kind}-{stage}.json')
        validate_expected(kind, expected)
        scratch = os.environ['FOUNDRY_SCRATCH_DIR'] if kind == 'doc' else None
    except Exception:
        report['checks'].append({'id': check_id, 'status': 'ERROR'})
        report['errors'].append(traceback.format_exc())
    else:
        try:
            if kind == 'doc':
                diagnostic = checker.check_doc(target, expected, scratch=scratch)
            else:
                diagnostic = checker.check_api(target, expected, live=True, service_state=state)
            report['checks'].append({'id': check_id, 'status': 'PASS'})
            report['diagnostic'] = diagnostic
        except (AssertionError, json.JSONDecodeError, KeyError, TypeError, IndexError,
                AttributeError, SyntaxError, UnicodeError) as error:
            target_phase = kind == 'doc' or state.get('phase') == 'TARGET_CONTRACT'
            target_syntax = (not isinstance(error, SyntaxError) or error.filename is not None
                             and Path(error.filename).resolve().is_relative_to(Path(target).resolve()))
            if target_phase and target_syntax:
                report['checks'].append({'id': check_id, 'status': 'FAIL'})
                report['failure_kind'] = 'ASSERTION'
                report['diagnostic'] = str(error)
            else:
                report['checks'].append({'id': check_id, 'status': 'ERROR'})
                report['errors'].append(traceback.format_exc())
        except Exception:
            report['checks'].append({'id': check_id, 'status': 'ERROR'})
            report['errors'].append(traceback.format_exc())
    if kind == 'api':
        report['services_started'] = state.get('services_started') is True
        report['services_stopped'] = state['services_stopped'] is True
        report['checks'].append({'id': 'owned-service-cleanup',
                                 'status': 'PASS' if report['services_stopped'] else 'ERROR'})
        if not report['services_stopped']:
            report['errors'].append('owned-service shutdown was not confirmed')
    if report['errors']:
        report.pop('failure_kind', None)
    passed = not report['errors'] and all(row['status'] == 'PASS' for row in report['checks'])
    report['status'] = 'CHECKS_PASS' if passed else 'CHECKS_FAILED'
    (report_dir/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', choices=['doc', 'api'], required=True)
    parser.add_argument('--stage', choices=['v1', 'v2', 'v3', 'incremental'], required=True)
    parser.add_argument('--target', type=Path, required=True)
    args = parser.parse_args()
    if args.kind == 'api' and args.stage == 'incremental':
        parser.error('incremental is the DOC project-only scenario')
    return run_checks(args.kind, args.stage, args.target)


if __name__ == '__main__':
    raise SystemExit(main())
