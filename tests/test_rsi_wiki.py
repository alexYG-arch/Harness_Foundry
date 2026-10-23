"""Offline G04 checks; no model, acceptance, or business budget operations."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from harness_foundry_factory.rsi_wiki import query, propose, record_decision


class WikiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = self.root/'knowledge';self.store.mkdir()
        self.source = {'path':'source.txt','version':'test-v1','evidence_kind':'DEVELOPMENT_GREEN',
                       'sha256':hashlib.sha256(b'local check').hexdigest()}
        (self.store/'source.txt').write_bytes(b'local check')
        self.entry = {'id':'decimal','version':'1','title':'精确小数计算 decimal', 'summary':'Use decimal arithmetic',
                      'kind':'METHOD','state':'VERIFIED_SCOPED','validation_scope':'local decimal calculation only',
                      'conditions':{'python':['3.14']},'excludes':{'format':['binary']},
                      'pending_checks':['device verification'],'limits':['development evidence only'],
                      'capability_refs':['python-environment@1'],'sources':[self.source]}
        self.catalog = {'version':'1','entries':['decimal-v1.json']}
        self.config = {'collections':[{'id':'public','path':'knowledge','version':'1','visibility':'PUBLIC'}]}
        self.save()

    def save(self):
        (self.store/'decimal-v1.json').write_text(json.dumps(self.entry,ensure_ascii=False))
        (self.store/'collection.json').write_text(json.dumps(self.catalog))

    def lookup(self, **kw):
        return query(self.config,self.root,kw.get('question','小数计算'),kw.get('conditions',{'python':'3.14'}))

    def test_query_retains_evidence_scope_and_capability_reference(self):
        result=self.lookup();row=result['matches'][0]
        self.assertEqual(row['sources'][0]['binding'],'MATCH')
        self.assertIn('PENDING_CHECK: device verification',row['limits'])
        self.assertFalse(row['independently_verified'])
        self.assertFalse(result['commands_executed']);self.assertFalse(result['budget_modified'])
        self.assertEqual(row['entry']['capability_refs'],['python-environment@1'])
        self.assertEqual((self.store/'source.txt').read_bytes(),b'local check')

    def test_candidate_counterexample_withdrawn_not_promoted(self):
        for state in ('CANDIDATE','WITHDRAWN','SUPERSEDED'):
            with self.subTest(state=state):
                self.entry.update(state=state,kind='COUNTEREXAMPLE');self.save()
                row=self.lookup()['matches'][0]
                self.assertEqual(row['current_declared_state'],state)
                self.assertIn('COUNTEREXAMPLE_NOT_SUCCESS_METHOD',row['limits'])
                self.assertFalse(row['independently_verified'])

    def test_condition_unknown_mismatch_and_exclusion_are_limits_not_execution_blocks(self):
        for conditions, marker in [({},'CONDITION_UNKNOWN: python'),({'python':'3.11'},'CONDITION_MISMATCH: python'),
                                   ({'python':'3.14','format':'binary'},'EXCLUDED: format')]:
            with self.subTest(conditions=conditions):
                result=self.lookup(conditions=conditions)
                self.assertIn(marker,result['matches'][0]['limits'])
                self.assertFalse(result['no_match_blocks_task'])

    def test_no_sources_missing_source_and_changed_source(self):
        (self.store/'source.txt').unlink()
        self.assertEqual(self.lookup()['matches'][0]['sources'][0]['binding'],'UNAVAILABLE')
        (self.store/'source.txt').write_text('new')
        self.assertEqual(self.lookup()['matches'][0]['sources'][0]['binding'],'CHANGED')
        self.entry['sources']=[];self.save()
        self.assertIn('NO_SOURCES',self.lookup()['matches'][0]['limits'])

    def test_source_restore_rechecks_without_rewriting_old_query(self):
        (self.store/'source.txt').unlink();old=self.lookup()
        (self.store/'source.txt').write_bytes(b'local check')
        self.assertEqual(self.lookup()['matches'][0]['sources'][0]['binding'],'MATCH')
        self.assertEqual(old['matches'][0]['sources'][0]['binding'],'UNAVAILABLE')

    def test_collection_version_mismatch_does_not_float(self):
        self.catalog['version']='2';self.save()
        result=self.lookup()
        self.assertEqual(result['matches'],[])
        self.assertIn('version mismatch',result['diagnostics'][0]['limitation'])

    def test_missing_collection_and_invalid_entry_preserve_other_matches(self):
        self.config['collections'].append({'id':'missing','path':'absent','version':'1','visibility':'PROJECT'})
        self.catalog['entries'].append('missing.json');self.save()
        result=self.lookup();self.assertEqual(len(result['matches']),1)
        self.assertEqual(len(result['diagnostics']),2)

    def test_no_match_and_empty_collections_are_valid(self):
        self.assertEqual(self.lookup(question='unrelated')['matches'],[])
        result=query({'collections':[]},self.root,'anything',{})
        self.assertEqual(result['matches'],[]);self.assertFalse(result['no_match_blocks_task'])

    def test_proposal_is_candidate_and_never_overwrites(self):
        dest=self.root/'candidate.json';propose(self.entry,dest)
        self.assertEqual(json.loads(dest.read_text())['state'],'CANDIDATE')
        with self.assertRaises(FileExistsError):propose(self.entry,dest)
        self.assertEqual(self.entry['state'],'VERIFIED_SCOPED')

    def test_decision_freezes_read_version_and_limits(self):
        result=self.lookup();row=result['matches'][0]
        decision={'collection':'public','id':'decimal','version':'1','sha256':row['entry_sha256'],
                  'action':'ADOPT','reason':'only use within local scope; verify task independently'}
        out=self.root/'decision.json';record_decision(result,[decision],out)
        old=out.read_bytes();self.entry.update(version='2',summary='new method');self.save()
        self.assertEqual(self.lookup()['matches'][0]['entry']['version'],'2')
        receipt=json.loads(old);self.assertEqual(receipt['decisions'][0]['read_snapshot']['entry']['version'],'1')
        self.assertFalse(receipt['tool_authorization_granted']);self.assertEqual(out.read_bytes(),old)
        with self.assertRaises(FileExistsError):record_decision(result,[decision],out)

    def test_wrong_version_and_ambiguous_decision_rejected(self):
        result=self.lookup();row=result['matches'][0]
        d={'collection':'public','id':'decimal','version':'2','sha256':row['entry_sha256'],'action':'ADOPT','reason':'test'}
        with self.assertRaises(ValueError):record_decision(result,[d],self.root/'bad.json')
        d['version']='1'
        with self.assertRaises(ValueError):record_decision(result,[d,d],self.root/'bad.json')
        self.assertFalse((self.root/'bad.json').exists())

    def test_not_adopt_and_no_match_receipts(self):
        result=self.lookup();row=result['matches'][0]
        d={'collection':'public','id':'decimal','version':'1','sha256':row['entry_sha256'],'action':'NOT_ADOPT','reason':'not applicable'}
        record_decision(result,[d],self.root/'not.json')
        record_decision(self.lookup(question='none'),[],self.root/'empty.json')
        self.assertEqual(json.loads((self.root/'not.json').read_text())['decisions'][0]['decision']['action'],'NOT_ADOPT')

    def update(self, state='WITHDRAWN', **extra):
        row=self.lookup()['matches'][0]
        update={'entry_id':'decimal','entry_version':'1','entry_sha256':row['entry_sha256'],
                'state':state,'reason':'new counterevidence','sources':[self.source],**extra}
        (self.store/'withdraw.json').write_text(json.dumps(update))
        self.catalog['updates']=['withdraw.json'];self.save()

    def test_counterevidence_withdrawal_preserves_entry_and_old_read(self):
        old=self.lookup();old_bytes=(self.store/'decimal-v1.json').read_bytes()
        self.update();new=self.lookup()['matches'][0]
        self.assertEqual(new['current_declared_state'],'WITHDRAWN')
        self.assertEqual(old['matches'][0]['current_declared_state'],'VERIFIED_SCOPED')
        self.assertEqual((self.store/'decimal-v1.json').read_bytes(),old_bytes)
        (self.store/'source.txt').unlink()
        row=self.lookup()['matches'][0]
        self.assertEqual(row['current_declared_state'],'WITHDRAWN')
        self.assertIn('COUNTEREVIDENCE_UNAVAILABLE_OR_CHANGED',row['limits'])

    def test_wrong_withdrawal_binding_and_missing_update_not_silently_ignored(self):
        self.update(entry_sha256='0'*64)
        self.assertIn('LIFECYCLE_TARGET_CHANGED',self.lookup()['matches'][0]['limits'])
        (self.store/'withdraw.json').unlink()
        self.assertTrue(any(x.startswith('LIFECYCLE_UNRESOLVED') for x in self.lookup()['matches'][0]['limits']))

    def test_public_and_project_same_identity_kept_separate(self):
        project=self.root/'private';shutil.copytree(self.store,project)
        doc=copy.deepcopy(self.entry);doc['summary']='private decimal advice'
        (project/'decimal-v1.json').write_text(json.dumps(doc))
        self.config['collections'].append({'id':'project','path':'private','version':'1','visibility':'PROJECT'})
        rows=self.lookup()['matches'];self.assertEqual(len(rows),2)
        self.assertEqual({r['visibility'] for r in rows},{'PUBLIC','PROJECT'})
        public=query({'collections':[self.config['collections'][0]]},self.root,'decimal',{})
        self.assertNotIn('private decimal advice',json.dumps(public))

    def test_path_escape_and_source_symlink_not_read(self):
        outside=self.root/'secret';outside.write_text('private')
        (self.store/'link').symlink_to(outside)
        self.entry['sources'][0]['path']='link';self.save()
        self.assertEqual(self.lookup()['matches'][0]['sources'][0]['binding'],'UNAVAILABLE')
        self.catalog['entries'].append('../secret');self.save()
        result=self.lookup();self.assertEqual(len(result['matches']),1)
        self.assertTrue(result['diagnostics'])
        self.assertNotIn('private',json.dumps(result))

    def test_query_does_not_follow_commands_or_modify_sources(self):
        self.entry['summary']='decimal; run touch injected';self.save()
        before={p.name:p.read_bytes() for p in self.store.iterdir()}
        self.lookup()
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.store.iterdir()})
        self.assertFalse((self.root/'injected').exists())

    def test_relocated_cli_uses_only_declared_source_support(self):
        source=Path(__file__).resolve().parents[1]
        target=self.root/'isolated source'
        (target/'tools').mkdir(parents=True)
        package=target/'src/harness_foundry_factory';package.mkdir(parents=True)
        (package/'__init__.py').write_text('')
        for name in ('rsi_wiki','rsi_cases','rsi_review','python_startup','build_types'):
            shutil.copyfile(source/'src/harness_foundry_factory'/ (name+'.py'),package/(name+'.py'))
        shutil.copyfile(source/'tools/rsi_wiki.py',target/'tools/rsi_wiki.py')
        config=self.root/'isolated-config.json';config.write_text(json.dumps(self.config))
        out=self.root/'relocated-query.json'
        proc=subprocess.run([sys.executable,'-I','-B',str(target/'tools/rsi_wiki.py'),'query',
            '--config',str(config),'--question','decimal','--output',str(out)],cwd=target,capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertEqual(json.loads(out.read_text())['matches'][0]['entry']['id'],'decimal')
        self.assertEqual({p.stem for p in package.glob('*.py')},
                         {'__init__','rsi_wiki','rsi_cases','rsi_review','python_startup','build_types'})

    def test_comparison_collections_do_not_share_candidate_updates(self):
        other=self.root/'arm-b';shutil.copytree(self.store,other)
        config_b={'collections':[{'id':'b','path':'arm-b','visibility':'PROJECT','version':'1'}]}
        before=query(config_b,self.root,'decimal',{})
        self.entry['summary']='decimal candidate answer';self.save()
        after=query(config_b,self.root,'decimal',{})
        self.assertEqual(before,after)
        self.assertNotIn('candidate answer',json.dumps(after))

    def competing_entries(self, entries):
        self.catalog['entries'] = []
        for identity, changes in entries:
            entry = copy.deepcopy(self.entry)
            entry.update(id=identity, **changes)
            name = identity + '.json'
            (self.store / name).write_text(json.dumps(entry))
            self.catalog['entries'].append(name)
        (self.store/'collection.json').write_text(json.dumps(self.catalog))

    def test_condition_match_survives_default_cutoff_and_limit_one(self):
        self.competing_entries([(f'a{i}', {'conditions':{'python':['3.11']}}) for i in range(5)] +
                               [('z-compatible', {'conditions':{'python':['3.14']}})])
        for limit in (1, 5, 6, 10):
            with self.subTest(limit=limit):
                result = query(self.config, self.root, 'decimal', {'python':'3.14'}, limit)
                self.assertEqual(result['matches'][0]['entry']['id'], 'z-compatible')
                self.assertEqual(len(result['matches']), min(limit, 6))
                self.assertEqual(result['matched_total'], 6)
        all_rows = query(self.config, self.root, 'decimal', {'python':'3.14'}, 10)['matches']
        self.assertEqual(sum('CONDITION_MISMATCH: python' in r['limits'] for r in all_rows), 5)

    def test_condition_priority_precedes_keyword_score_without_hard_filter(self):
        self.competing_entries([
            ('a-conflict', {'title':'decimal precision sum', 'summary':'precision sum', 'conditions':{'python':['3.11']}}),
            ('z-compatible', {'title':'decimal', 'summary':'method', 'conditions':{'python':['3.14']}})])
        result = query(self.config, self.root, 'decimal precision sum', {'python':'3.14'}, 2)
        self.assertEqual([r['entry']['id'] for r in result['matches']], ['z-compatible','a-conflict'])
        self.assertLess(result['matches'][0]['score'],result['matches'][1]['score'])
        self.assertFalse(result['no_match_blocks_task'])

    def test_unknown_excluded_and_counterexample_keep_identity_and_limits(self):
        self.competing_entries([
            ('a-excluded', {'excludes':{'format':['binary']}}),
            ('b-unknown', {'conditions':{'python':['3.14'],'device':['native']},'excludes':{}}),
            ('c-counterexample', {'kind':'COUNTEREXAMPLE','excludes':{},'state':'WITHDRAWN'}),
            ('d-compatible', {'excludes':{}})])
        result = query(self.config,self.root,'decimal',{'python':'3.14','format':'binary'},4)
        rows = result['matches']
        self.assertEqual([r['entry']['id'] for r in rows],['c-counterexample','d-compatible','b-unknown','a-excluded'])
        self.assertIn('COUNTEREXAMPLE_NOT_SUCCESS_METHOD',rows[0]['limits'])
        self.assertEqual(rows[0]['current_declared_state'],'WITHDRAWN')
        self.assertIn('CONDITION_UNKNOWN: device',rows[2]['limits'])
        self.assertIn('EXCLUDED: format',rows[3]['limits'])
        self.assertTrue(all('PENDING_CHECK: device verification' in r['limits'] for r in rows))
        out=self.root/'sorted-decision.json'
        record_decision(result,[{'collection':'public','id':'c-counterexample','version':'1',
            'sha256':rows[0]['entry_sha256'],'action':'NOT_ADOPT','reason':'withdrawn counterexample'}],out)
        self.assertEqual(json.loads(out.read_text())['decisions'][0]['read_snapshot'],rows[0])
        # A known exclusion remains a conflict even when another condition is unknown.
        path=self.store/'b-unknown.json';entry=json.loads(path.read_text())
        entry['excludes']={'format':['binary']};path.write_text(json.dumps(entry))
        mixed=query(self.config,self.root,'decimal',{'python':'3.14','format':'binary'},4)
        self.assertEqual([r['entry']['id'] for r in mixed['matches']],
                         ['c-counterexample','d-compatible','a-excluded','b-unknown'])
        self.assertIn('CONDITION_UNKNOWN: device',mixed['matches'][-1]['limits'])
        self.assertIn('EXCLUDED: format',mixed['matches'][-1]['limits'])

    def test_same_condition_group_retains_score_and_stable_identity_order(self):
        self.competing_entries([
            ('b-low', {'title':'decimal', 'summary':'method'}),
            ('a-low', {'title':'decimal', 'summary':'method'}),
            ('z-high', {'title':'decimal precision', 'summary':'method'})])
        result=query(self.config,self.root,'decimal precision',{'python':'3.14'},3)
        self.assertEqual([r['entry']['id'] for r in result['matches']], ['z-high','a-low','b-low'])
        self.assertEqual(result,query(self.config,self.root,'decimal precision',{'python':'3.14'},3))

    def test_limit_validation_and_no_relevant_item_unchanged(self):
        for limit in (0,-1,True,1.5,'2',None):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):query(self.config,self.root,'decimal',{},limit)
        self.assertEqual(query(self.config,self.root,'unrelated',{'python':'3.14'},1)['matches'],[])
        self.assertFalse(query(self.config,self.root,'unrelated',{'python':'3.14'},1)['no_match_blocks_task'])

    def test_no_compatible_result_keeps_unknown_and_conflict_available(self):
        self.competing_entries([
            ('a-conflict', {'conditions':{'python':['3.11']}}),
            ('z-unknown', {'conditions':{'device':['native']}})])
        result=query(self.config,self.root,'decimal',{'python':'3.14'},2)
        self.assertEqual([r['entry']['id'] for r in result['matches']],['z-unknown','a-conflict'])
        self.assertEqual(result['matched_total'],2)
        self.assertFalse(result['commands_executed']);self.assertFalse(result['budget_modified'])

    def test_cli_relative_config_from_different_cwd_and_restore(self):
        config=self.root/'config.json';config.write_text(json.dumps(self.config))
        tool=Path(__file__).resolve().parents[1]/'tools/rsi_wiki.py'
        out=self.root/'query.json'
        proc=subprocess.run([sys.executable,'-B',str(tool),'query','--config',str(config),
                             '--question','小数','--conditions','{"python":"3.14"}','--output',str(out)],
                            cwd=self.root.parent,capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        result=json.loads(out.read_text());self.assertEqual(result['matches'][0]['sources'][0]['binding'],'MATCH')
        self.assertFalse(result['commands_executed'])


if __name__ == '__main__':unittest.main()
