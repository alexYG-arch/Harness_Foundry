"""E4 material integration only; no model, telemetry or business acceptance."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / 'examples/capability-adapters/rsi_handoff.py'
spec = importlib.util.spec_from_file_location('tested_rsi_handoff', ENTRY)
H = importlib.util.module_from_spec(spec); spec.loader.exec_module(H)


class RSIHandoffTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='RSI 混用 ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.raw = self.root / 'raw'; self.raw.mkdir()
        self.output = self.root / 'analysis'
        self.result = {'status': 'FAIL', 'prepared_event_id': 'p1', 'attempt_id': 'a1',
                       'budget': {'used': 3, 'remaining': 2}, 'message': 'private-oracle TOKEN:SYNTHETIC'}
        self.save('result.json', self.result)
        self.request = {'enabled': True, 'identity': {'project': 'project', 'task': 'task', 'issue': 'issue'},
            'phase': 'return', 'context': {'prepared': 'p1', 'attempt': 'a1', 'command': 'c1'},
            'case': {'case_id': 'issue', 'goal': 'diagnose source result', 'requirements': ['public result'],
                     'sources': [{'source_id': 's', 'path': 'result.json', 'kind': 'FOUNDRY_REPORT'}]},
            'references': [{'role': 'existing-controller-report', 'path': 'result.json'}]}

    def save(self, name, data):
        path = self.raw / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def capture(self):
        return H.capture(self.request, self.raw, self.output)

    def contents(self, root):
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in Path(root).rglob('*') if p.is_file()}

    def test_unselected_requires_no_case_root_output_or_execution(self):
        with patch('subprocess.Popen', side_effect=AssertionError('no execution')):
            for function in (H.capture, H.collection):
                got = function({}, self.root / 'missing', self.output)
                self.assertEqual(got['status'], 'NOT_SELECTED')
        self.assertFalse(self.output.exists())

    def test_case_budget_and_reference_preserved_without_execution(self):
        before = self.contents(self.raw)
        with patch('subprocess.Popen', side_effect=AssertionError('no execution')):
            got = self.capture()
        case = json.loads((Path(got['directory']) / 'case.json').read_text())
        self.assertEqual(case['sources'][0]['document'], self.result)
        self.assertFalse(got['business_state_modified']); self.assertFalse(got['budget_modified'])
        self.assertFalse(got['acceptance_verified']); self.assertEqual(before, self.contents(self.raw))
        self.assertEqual(got['references'][0]['observation']['status'], 'READ')

    def test_same_input_reuses_complete_report_without_reimport(self):
        first = self.capture(); before = self.contents(self.output)
        with patch.object(H.rsi_cases, 'import_case', side_effect=AssertionError('must retrieve')):
            second = self.capture(); third = self.capture()
        self.assertTrue(second['reused']); self.assertEqual(second, third)
        self.assertEqual(first['directory'], second['directory']); self.assertEqual(before, self.contents(self.output))

    def test_written_files_without_receipt_are_recovered_unchanged(self):
        first = self.capture(); p = Path(first['directory']); (p / 'completion.json').unlink()
        before = self.contents(p); got = self.capture()
        self.assertTrue(got['receipt_recovered']); self.assertEqual(first['directory'], got['directory'])
        self.assertEqual(before, {k: v for k, v in self.contents(p).items() if k != 'completion.json'})

    def test_partial_or_changed_output_preserved_and_revised(self):
        first = self.capture(); p = Path(first['directory'])
        (p / 'case.json').write_text('{partial')
        before = self.contents(p); second = self.capture()
        self.assertFalse(second['reused']); self.assertNotEqual(first['directory'], second['directory'])
        self.assertEqual(before, self.contents(p)); self.assertEqual(second['status'], 'COMPLETE')

    def test_cross_prepared_and_recheck_preserve_problem_and_old_consumption(self):
        first = self.capture(); before = self.contents(Path(first['directory']))
        self.request['context'] = {'prepared': 'p2', 'attempt': 'check-only-1', 'production_attempt': 'a1', 'command': 'verify-c2'}
        second = self.capture()
        self.assertEqual(first['identity'], second['identity']); self.assertNotEqual(first['directory'], second['directory'])
        self.assertEqual(before, self.contents(Path(first['directory'])))
        case = json.loads((Path(second['directory']) / 'case.json').read_text())
        self.assertEqual(case['sources'][0]['document']['budget'], {'used': 3, 'remaining': 2})

    def test_similar_different_projects_or_issues_do_not_merge(self):
        first = self.capture()
        for key in ('project', 'task', 'issue'):
            old = self.request['identity'][key]; self.request['identity'][key] = 'different'
            new = self.capture(); self.assertNotEqual(first['directory'], new['directory'])
            self.request['identity'][key] = old
        self.assertEqual(first['directory'], self.capture()['directory'])

    def test_new_evidence_or_tool_version_creates_revision(self):
        first = self.capture()
        self.result['status'] = 'PASS'; self.save('result.json', self.result)
        second = self.capture(); self.assertNotEqual(first['directory'], second['directory'])
        version = H.versions(); version['rsi_cases'] = 'new-version'
        with patch.object(H, 'versions', return_value=version):
            third = self.capture()
        self.assertNotEqual(second['directory'], third['directory'])
        self.assertEqual(json.loads((Path(first['directory']) / 'case.json').read_text())['sources'][0]['document']['status'], 'FAIL')

    def test_missing_source_retains_facts_refs_then_restoration_rechecks(self):
        self.request['case']['sources'].append({'source_id': 'later', 'path': 'later.txt', 'kind': 'TEXT_LOG'})
        self.request['case']['hypotheses'] = [{'id': 'h', 'owner': 'UNKNOWN', 'statement': 'unconfirmed', 'support_refs': ['later#L1']}]
        first = self.capture(); self.assertEqual(first['status'], 'PARTIAL')
        report = json.loads((Path(first['directory']) / 'case.json').read_text())
        self.assertEqual(report['hypotheses'][0]['unverified_refs'], ['later#L1'])
        self.assertEqual(report['observations'][0]['reported_status'], 'FAIL')
        (self.raw / 'later.txt').write_text('FAIL')
        second = self.capture(); self.assertEqual(second['status'], 'COMPLETE')
        self.assertNotEqual(first['directory'], second['directory'])
        self.request['case']['hypotheses'][0]['support_refs'] = ['later#L99']
        with self.assertRaisesRegex(ValueError, 'unresolved evidence'): self.capture()

    def test_missing_reference_does_not_discard_known_case(self):
        self.request['references'].append({'role': 'reviewer', 'path': 'missing.json'})
        got = self.capture(); self.assertEqual(got['status'], 'PARTIAL')
        self.assertEqual(got['references'][1]['observation']['status'], 'UNAVAILABLE')
        self.assertTrue((Path(got['directory']) / 'case.json').exists())

    def test_source_change_during_build_does_not_save_misbound_case(self):
        original = H.rsi_cases.import_case
        def changed(*args):
            result = original(*args); self.result['status'] = 'PASS'; self.save('result.json', self.result)
            return result
        with patch.object(H.rsi_cases, 'import_case', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'input changed'): self.capture()
        self.assertFalse(self.output.exists())

    def test_root_escape_rejected_without_following_unknown_materials(self):
        (self.root / 'outside').write_text('private')
        for name in ('../outside', str(self.root / 'outside')):
            self.request['case']['sources'][0]['path'] = name
            with self.assertRaises(ValueError): self.capture()
        (self.raw / 'link').symlink_to(self.root / 'outside')
        self.request['case']['sources'][0]['path'] = 'link'
        with self.assertRaises(ValueError): self.capture()

    def test_tdd_reuses_existing_association_and_preserves_suite(self):
        from tests.test_rsi_tdd import RSITddTests
        fixture = RSITddTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        for p in fixture.root.iterdir(): shutil.copyfile(p, self.raw / p.name)
        self.request['case'] = fixture.manifest; self.request['tdd'] = fixture.association
        self.request['tdd']['cycles'][0]['regression'] = {'status': 'FAIL', 'reference': 'whole-suite'}
        self.request['references'] = []
        got = self.capture(); tdd = json.loads((Path(got['directory']) / 'tdd.json').read_text())
        self.assertEqual(tdd['cycles'][0]['evidence_pair_status'], 'COMPARABLE_REPORTED_RED_GREEN')
        self.assertEqual(tdd['cycles'][0]['regression']['status'], 'FAIL')
        self.assertFalse(tdd['acceptance_verified']); self.assertFalse(tdd['full_tdd_verified'])
        self.request['tdd']['cycles'][0].pop('red')
        got = self.capture(); tdd = json.loads((Path(got['directory']) / 'tdd.json').read_text())
        self.assertEqual(tdd['cycles'][0]['classification'], 'GREEN_ONLY')

    def knowledge(self):
        self.save('public-check.json', {'result': 'synthetic rejected bug and legal counterpart'})
        source = {'path': 'evidence/check.json', 'sha256': H.sha((self.raw / 'public-check.json').read_bytes()),
                  'version': 'test-v1', 'evidence_kind': 'DEVELOPMENT_GREEN'}
        self.entry = {'id': 'method', 'version': '1', 'title': 'decimal method', 'summary': 'synthetic example',
                      'state': 'CANDIDATE', 'kind': 'METHOD', 'sources': [source], 'conditions': {'python': ['3']}}
        self.save('entry.json', self.entry)
        self.selection = {'enabled': True, 'identity': deepcopy(self.request['identity']), 'phase': 'knowledge-return',
                          'collection': {'id': 'selected', 'version': '1', 'visibility': 'PUBLIC'},
                          'entries': ['entries/method.json'], 'updates': [], 'files': [
                              {'source': 'entry.json', 'path': 'entries/method.json', 'audience': 'PUBLIC', 'reason': 'synthetic summary'},
                              {'source': 'public-check.json', 'path': 'evidence/check.json', 'audience': 'PUBLIC', 'reason': 'synthetic regression only'}]}
        return self.selection

    def lookup(self, got, conditions=None):
        directory = Path(got['directory'])
        return H.rsi_wiki.query(json.loads((directory / 'wiki.json').read_text()), directory,
                               'decimal method', conditions or {})

    def test_selected_collection_query_and_private_material_not_copied(self):
        analysis = self.capture(); self.knowledge()
        got = H.collection(self.selection, self.raw, self.root / 'knowledge')
        query = self.lookup(got); row = query['matches'][0]
        self.assertEqual(row['sources'][0]['binding'], 'MATCH')
        self.assertEqual(row['entry']['state'], 'CANDIDATE')
        self.assertIn('CONDITION_UNKNOWN: python', row['limits'])
        content = b''.join(self.contents(Path(got['directory']) / 'collection').values())
        self.assertNotIn(b'private-oracle', content); self.assertNotIn(b'TOKEN:SYNTHETIC', content)
        self.assertIn('private-oracle', (Path(analysis['directory']) / 'case.json').read_text())
        second = H.collection(self.selection, self.raw, self.root / 'knowledge')
        self.assertTrue(second['reused']); self.assertEqual(got['directory'], second['directory'])

    def test_collection_new_version_and_withdrawal_leave_old_adoption_unchanged(self):
        self.knowledge(); first = H.collection(self.selection, self.raw, self.root / 'knowledge')
        query = self.lookup(first); row = query['matches'][0]
        adopted = self.root / 'adoption.json'
        H.rsi_wiki.record_decision(query, [{'collection': 'selected', 'id': 'method', 'version': '1',
            'sha256': row['entry_sha256'], 'action': 'NOT_ADOPT', 'reason': 'new task conditions differ'}], adopted)
        old = self.contents(Path(first['directory'])); saved = adopted.read_bytes()
        self.save('prior.json', json.loads((Path(first['directory']) / 'wiki.json').read_text()))
        self.selection.update(previous_config='prior.json'); self.selection['collection']['version'] = '2'
        self.save('withdraw.json', {'entry_id': 'method', 'entry_version': '1', 'entry_sha256': row['entry_sha256'],
            'state': 'WITHDRAWN', 'reason': 'counterexample', 'sources': self.entry['sources']})
        self.selection['updates'] = ['withdraw.json']; self.selection['files'].append({
            'source': 'withdraw.json', 'path': 'withdraw.json', 'audience': 'PUBLIC', 'reason': 'public counterexample'})
        second = H.collection(self.selection, self.raw, self.root / 'knowledge')
        self.assertEqual(self.lookup(second)['matches'][0]['current_declared_state'], 'WITHDRAWN')
        self.assertEqual(old, self.contents(Path(first['directory']))); self.assertEqual(saved, adopted.read_bytes())
        self.selection['collection']['version'] = '1'
        with self.assertRaisesRegex(ValueError, 'new collection version'):
            H.collection(self.selection, self.raw, self.root / 'knowledge')

    def test_collection_missing_source_stays_insufficient_not_silently_copied(self):
        self.knowledge(); self.selection['files'].pop()
        got = H.collection(self.selection, self.raw, self.root / 'knowledge')
        self.assertEqual(self.lookup(got)['matches'][0]['sources'][0]['binding'], 'UNAVAILABLE')
        self.assertFalse(self.lookup(got)['no_match_blocks_task'])

    def test_selection_requires_explicit_audience_and_listed_entry(self):
        self.knowledge(); self.selection['files'][0]['audience'] = 'PROJECT'
        with self.assertRaises(ValueError): H.collection(self.selection, self.raw, self.root / 'knowledge')
        self.selection['files'][0]['audience'] = 'PUBLIC'; self.selection['files'].pop(0)
        with self.assertRaisesRegex(ValueError, 'entry/update file missing'):
            H.collection(self.selection, self.raw, self.root / 'knowledge')

    def test_cli_failure_is_handoff_gap_not_business_failure_or_secret_log(self):
        self.request['case']['hypotheses'] = [{'id': 'h', 'owner': 'UNKNOWN', 'statement': 'private-oracle', 'support_refs': ['s#MISSING']}]
        self.save('request.json', self.request); before = self.contents(self.raw)
        command = [sys.executable, '-I', '-B', str(ENTRY), 'capture', '--manifest', str(self.raw / 'request.json'), '--output', str(self.output)]
        run = subprocess.run(command, capture_output=True, text=True, timeout=20)
        self.assertEqual(run.returncode, 2); row = json.loads(run.stdout)
        self.assertEqual(row['status'], 'HANDOFF_INCOMPLETE'); self.assertFalse(row['business_state_modified'])
        self.assertNotIn('private-oracle', run.stdout + run.stderr); self.assertEqual(before, self.contents(self.raw))

    def test_unwritable_destination_preserves_case_and_does_not_dispatch(self):
        before = self.contents(self.raw); self.output.write_text('existing non-directory')
        with patch('subprocess.Popen', side_effect=AssertionError('no dispatch')):
            with self.assertRaises(OSError): self.capture()
        self.assertEqual(before, self.contents(self.raw)); self.assertEqual(self.output.read_text(), 'existing non-directory')

    def test_native_and_builtin_same_tool_role_stay_separate(self):
        from tests.test_capability_native import NativeCapabilityTests, P, C
        fixture = NativeCapabilityTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        package = fixture.project / 'builtin'; package.mkdir()
        (package / 'method.md').write_text('Local builtin calculation')
        (package / 'tool.py').write_text('print("builtin")')
        (package / 'capability.json').write_text(json.dumps({'name': 'local', 'version': '1', 'usage': 'both',
            'inputs': ['text'], 'outputs': ['text'], 'materials': ['method.md'], 'verification_files': [],
            'environment': [{'id': 'python', 'kind': 'executable'}],
            'tools': [{'id': 'echo', 'path': 'tool.py', 'interpreter': 'python'}]}))
        config = {'project_root': str(fixture.project), 'selections': [{'directory': 'builtin', 'version': '1', 'workpack_ids': []}],
            'environment_bindings': {'python': {'path': sys.executable}},
            'connections': {'instance_root': str(fixture.instance), 'native': [fixture.config]}}
        materials, _ = P.build_materials(config, fixture.root / 'mixed')
        inner = C.prepare_call(materials, 'echo'); outer = C.prepare_call(materials, 'instance.demo.echo')
        self.assertEqual(inner['argv'][-1], str(package / 'tool.py'))
        self.assertEqual(outer['argv'][-1], str(fixture.package / 'tool.py'))
        self.assertIn('python', materials['scope_fragment']['executables'])
        self.assertIn('instance.demo.python', materials['scope_fragment']['executables'])
        self.assertFalse(inner['acceptance_granted']); self.assertFalse(outer['acceptance_granted'])


    def test_incomplete_receipt_shape_is_preserved_as_new_revision(self):
        first = self.capture(); path = Path(first['directory']) / 'completion.json'
        receipt = json.loads(path.read_text()); receipt['files'] = ['incomplete manifest']
        path.write_text(json.dumps(receipt)); old = path.read_bytes()
        second = self.capture()
        self.assertNotEqual(first['directory'], second['directory'])
        self.assertEqual(path.read_bytes(), old)

    def test_source_and_shipping_skill_share_selected_trigger_and_boundaries(self):
        sections = []
        for name in ('.agents/skills/harness-foundry-start-author/SKILL.md', 'resources/generic_release/SKILL.md'):
            text = (ROOT / name).read_text()
            sections.append(text.split('## Selected repair RSI handoff', 1)[1])
        self.assertEqual(*sections)
        for phrase in ('proactively', 'same project/task/problem', 'do not wait', 'Do not interrupt',
                       'No selected RSI', 'never replay', 'Material failure', 'Target delivery'):
            self.assertIn(phrase, sections[0])
        self.assertTrue((ROOT / 'examples/capability-adapters/RSI_HANDOFF.md').is_file())

    def test_shipping_inventory_contains_complete_host_helper_and_guide(self):
        from devtools.package_generic_release import collect_files
        files = collect_files(ROOT)
        for name in ('examples/capability-adapters/rsi_handoff.py', 'examples/capability-adapters/RSI_HANDOFF.md'):
            self.assertEqual(files[name], (ROOT / name).read_bytes())
        for module in ('rsi_cases', 'rsi_tdd', 'rsi_wiki', 'rsi_review', 'build_types', 'python_startup'):
            self.assertIn('src/harness_foundry_factory/' + module + '.py', files)


if __name__ == '__main__': unittest.main()
