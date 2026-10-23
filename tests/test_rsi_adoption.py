"""Optional adoption association and existing upgrade-helper integration, no model."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from harness_foundry_factory.rsi_adoption import report_adoption, snapshot
from harness_foundry_factory.rsi_cases import write_case
from harness_foundry_factory.rsi_delivery import prepare_delivery

ROOT = Path(__file__).resolve().parents[1]


class RSIAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'product').mkdir()
        (self.root/'product/adapter.py').write_text('old behavior')
        self.snap = snapshot(self.root/'product', ['adapter.py'], 'candidate-1')
        self.manifest = {'owner': 'HARNESS', 'decision': {'action': 'RETAIN', 'selected': 'candidate', 'reason': 'Scoped behavior repaired'},
                         'artifacts': {'candidate': {**self.save('snapshot.json', self.snap), 'root': 'product'}},
                         'evidence': [], 'historical_budget': {'production': 4, 'remaining': 2},
                         'adoption_stages': {'project': 'FIXED', 'source': 'CANDIDATE', 'package': 'NOT_BUILT', 'deployment': 'NOT_UPGRADED'}}
        self.add_check()

    def save(self, name, data):
        raw = json.dumps(data).encode(); (self.root/name).write_bytes(raw)
        return {'path': name, 'sha256': hashlib.sha256(raw).hexdigest()}

    def add_check(self, role='REGRESSION', status='PASS', name='check'):
        self.manifest['evidence'].append({'id': name, 'role': role, 'subject': 'candidate',
            'subject_sha256': self.snap['content_sha256'], **self.save(name+'.json', {'status': status, 'tests': 1})})

    def report(self):
        return report_adoption(self.manifest, self.root)

    def test_bound_reports_are_not_acceptance_or_benefits(self):
        r = self.report(); self.assertEqual(r['association_status'], 'RECORDED')
        for field in ('commands_executed','budget_modified','acceptance_verified','decision_verified','benefit_verified','deployment_modified'):
            self.assertIs(r[field], False)
        self.assertEqual(r['manifest'], self.manifest)

    def test_final_source_change_retains_old_green_without_certifying_new_file(self):
        (self.root/'product/adapter.py').write_text('refactored behavior')
        r = self.report(); self.assertEqual(r['artifacts']['candidate']['state'], 'CHANGED')
        self.assertEqual(r['evidence'][0]['record']['status'], 'PASS')
        self.assertEqual(r['evidence'][0]['state'], 'UNAVAILABLE')
        self.assertEqual(r['association_status'], 'EVIDENCE_GAPS')

    def test_same_label_other_snapshot_not_reused(self):
        self.manifest['evidence'][0]['subject_sha256'] = '0'*64
        self.assertEqual(self.report()['evidence'][0]['state'], 'UNAVAILABLE')

    def test_report_change_does_not_overwrite_old_binding(self):
        (self.root/'check.json').write_text('{"status":"FAIL"}')
        r = self.report(); self.assertEqual(r['evidence'][0]['binding'], self.manifest['evidence'][0])
        self.assertEqual(r['evidence'][0]['state'], 'UNAVAILABLE')

    def test_single_missing_source_preserves_known_fail_and_budget(self):
        self.add_check('INDEPENDENT_CHECK', 'FAIL', 'independent')
        (self.root/'check.json').unlink()
        r = self.report(); self.assertEqual(r['evidence'][1]['record']['status'], 'FAIL')
        self.assertEqual(r['evidence'][1]['state'], 'BOUND')
        self.assertEqual(r['manifest']['historical_budget'], {'production': 4, 'remaining': 2})

    def test_fail_skip_unknown_remain_original_not_upgraded_to_pass(self):
        for status in ('FAIL', 'SKIP', 'UNKNOWN', 'NOT_RUN'):
            with self.subTest(status=status):
                self.manifest['evidence'] = []; self.add_check(status=status)
                self.assertEqual(self.report()['evidence'][0]['record']['status'], status)
                self.assertFalse(self.report()['acceptance_verified'])

    def test_business_check_does_not_prove_mechanism_benefit(self):
        self.manifest['owner'] = 'PROJECT'
        self.manifest['scope'] = 'BUSINESS_FIX'
        self.manifest['comparison'] = {'reported_benefit': 'unknown', 'conditions': 'same local tools'}
        r = self.report(); self.assertEqual(r['manifest']['owner'], 'PROJECT')
        self.assertFalse(r['benefit_verified'])

    def test_foundry_case_and_own_behavior_check_keep_stages_separate(self):
        self.manifest['owner'] = 'FOUNDRY'
        case = {'case_id': 'generic-one', 'hypotheses': [{'owner': 'FOUNDRY', 'assessment': 'HYPOTHESIS_NOT_CONFIRMED'}]}
        self.manifest['evidence'].append({'id': 'case', 'role': 'CASE', **self.save('case.json', case)})
        r = self.report()
        self.assertEqual(r['evidence'][1]['record'], case)
        self.assertEqual(r['manifest']['adoption_stages']['deployment'], 'NOT_UPGRADED')
        self.assertFalse(r['decision_verified'])

    def test_development_green_not_substitute_for_behavior_regression(self):
        self.manifest['evidence'][0]['role'] = 'TDD'
        r = self.report(); self.assertEqual(r['association_status'], 'EVIDENCE_GAPS')
        self.assertEqual(r['evidence'][0]['state'], 'BOUND')

    def test_no_benefit_reject_without_forced_repair_or_missing_checks(self):
        self.manifest['decision'] = {'action': 'REJECT', 'reason': 'No measured improvement'}
        self.manifest['artifacts'] = {}; self.manifest['evidence'] = []
        self.assertEqual(self.report()['association_status'], 'RECORDED')
        self.assertFalse(self.report()['commands_executed'])

    def test_rollback_only_records_selected_checked_version(self):
        self.manifest['decision']['action'] = 'ROLLBACK'
        before = (self.root/'product/adapter.py').read_bytes()
        self.report()
        self.assertEqual((self.root/'product/adapter.py').read_bytes(), before)

    def test_read_twice_no_count_or_state_changes_and_old_output_immutable(self):
        r = self.report(); self.assertEqual(r, self.report())
        path = self.root/'adoption.json'; write_case(r, path); before = path.read_bytes()
        with self.assertRaises(FileExistsError): write_case(r, path)
        self.assertEqual(path.read_bytes(), before)

    def test_executable_and_absent_files_are_bound(self):
        path = self.root/'product/adapter.py'; path.chmod(0o644)
        a = snapshot(path.parent, ['adapter.py','removed.py'], 'v1')
        path.chmod(0o755)
        b = snapshot(path.parent, ['adapter.py','removed.py'], 'v1')
        self.assertNotEqual(a['content_sha256'], b['content_sha256'])
        self.assertEqual(a['files']['removed.py'], {'missing': True})

    def test_unselected_files_not_scanned(self):
        (self.root/'product/private.txt').write_text('not part of selection')
        self.assertEqual(self.report()['artifacts']['candidate']['state'], 'MATCH')
        self.assertNotIn('private.txt', json.dumps(self.report()))

    def test_legitimate_parent_alias_keeps_snapshot_identity(self):
        (self.root/'alias').symlink_to(self.root/'product', target_is_directory=True)
        self.assertEqual(snapshot(self.root/'alias', ['adapter.py'], 'candidate-1'), self.snap)

    def test_invalid_manifest_and_duplicate_evidence_rejected(self):
        self.manifest['evidence'].append(deepcopy(self.manifest['evidence'][0]))
        with self.assertRaisesRegex(ValueError, 'unique'): self.report()
        for files in ([], ['../escape'], ['adapter.py','adapter.py']):
            with self.assertRaises(ValueError): snapshot(self.root, files, 'v')

    def test_source_restoration_rechecks_original_bytes(self):
        raw = (self.root/'check.json').read_bytes(); (self.root/'check.json').unlink()
        self.assertEqual(self.report()['evidence'][0]['state'], 'UNAVAILABLE')
        (self.root/'check.json').write_bytes(raw)
        self.assertEqual(self.report()['evidence'][0]['state'], 'BOUND')

    def test_helper_preserves_customization_and_conflict_then_report_keeps_it(self):
        spec = importlib.util.spec_from_file_location('rsi_existing_merge', ROOT/'examples/harness-composition-upgrade/helpers/merge.py')
        helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
        for name, value in [('c','custom'),('g','base'),('n','next')]:
            (self.root/name).write_text(value)
        payload = lambda name: {'file':name, 'executable':False}
        self.save('merge.json', {'format_version':1, 'files':[
            {'path':'custom.txt','C':payload('c'),'G':payload('g'),'N':payload('g')},
            {'path':'conflict.txt','C':payload('c'),'G':payload('g'),'N':payload('n')} ]})
        merged = helper.merge(self.root/'merge.json', self.root/'merge-output')
        self.assertEqual(merged['files'][0]['selected'], 'C')
        self.assertEqual(merged['files'][1]['status'], 'CONFLICT')
        self.manifest['decision'] = {'action':'DEFER', 'reason':'Resolve existing helper conflict'}
        self.manifest['evidence'].append({'id':'composition', 'role':'COMPOSITION', **self.save('merged.json',merged)})
        r = self.report(); self.assertEqual(r['evidence'][-1]['record'], merged)
        self.assertEqual((self.root/'c').read_text(), 'custom')

    def test_relocated_support_actual_cli_does_not_need_development_imports(self):
        out = self.root/'support'
        prepare_delivery(ROOT, {'version':'new-support'}, self.root, out)
        moved = self.root/'新 support'; out.rename(moved)
        manifest = self.root/'manifest.json'; manifest.write_text(json.dumps(self.manifest))
        command = [sys.executable,'-I','-S','-B',str(moved/'tools/report_rsi_adoption.py'),'report','--manifest',str(manifest)]
        for i in (1,2):
            p = self.root/f'report-{i}.json'
            r = subprocess.run(command+['--output',str(p)],cwd=self.root,env={**os.environ,'PYTHONPATH':'/not-a-development-tree'},capture_output=True,text=True,timeout=30)
            self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual((self.root/'report-1.json').read_bytes(),(self.root/'report-2.json').read_bytes())

    def test_capture_cli_binding_from_real_files(self):
        self.save('files.json',['adapter.py'])
        r = subprocess.run([sys.executable,'-I','-S','-B',str(ROOT/'tools/report_rsi_adoption.py'),
            'snapshot','--root',str(self.root/'product'),'--files',str(self.root/'files.json'),
            '--version','candidate-1','--output',str(self.root/'captured.json')],capture_output=True,text=True,timeout=30)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads((self.root/'captured.json').read_text()),self.snap)


if __name__ == '__main__': unittest.main()
