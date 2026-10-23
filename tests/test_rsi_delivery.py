"""Real isolated CLI calls on selected handoff files; semantic model acceptance excluded."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from harness_foundry_factory.rsi_delivery import prepare_delivery
from harness_foundry_factory.rsi_review import digest
from tests import test_rsi_tdd as tdd_fixtures
from tests import test_rsi_review as review_fixtures

ROOT = Path(__file__).resolve().parents[1]


class RSIDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.materials = self.root / 'materials'; self.materials.mkdir()
        self.output = self.root / 'harness support'
        self.manifest = {'version': '1', 'wiki': {'collections': []}, 'knowledge_files': []}

    def deliver(self):
        return prepare_delivery(ROOT, self.manifest, self.materials, self.output)

    def cli(self, tool, *args, ok=True):
        result = subprocess.run([sys.executable, '-I', '-S', '-B', str(self.output/'tools'/tool), *map(str,args)],
            cwd=self.root, env={**os.environ, 'PYTHONPATH':'/missing/development-tree'}, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0 if ok else 2, result.stderr)
        return result

    def knowledge(self):
        k=self.materials/'knowledge/public'; k.mkdir(parents=True)
        source=b'Unittest skip is not a passing test. Inspect failures independently.\n'
        (k/'source.txt').write_bytes(source)
        entry={'id':'test-results','version':'1','title':'test skip failure',
               'summary':'Keep skips and failures distinct','kind':'METHOD','state':'CANDIDATE',
               'conditions':{},'excludes':{},'limits':['Method guidance, not a task verdict'],
               'pending_checks':['independent task outcome'], 'capability_refs':[],
               'sources':[{'path':'source.txt','version':'1','sha256':hashlib.sha256(source).hexdigest(),
                           'evidence_kind':'REFERENCE'}]}
        (k/'entry.json').write_text(json.dumps(entry)); (k/'collection.json').write_text(json.dumps({'version':'1','entries':['entry.json']}))
        self.manifest['wiki']['collections']=[{'id':'public','path':'knowledge/public','version':'1','visibility':'PUBLIC'}]
        self.manifest['knowledge_files']=['knowledge/public/'+p for p in ('source.txt','entry.json','collection.json')]

    def test_relocated_delivery_has_exact_dependencies_and_no_authority(self):
        receipt=self.deliver()
        self.assertFalse(receipt['runtime_authorized']); self.assertFalse(receipt['budget_modified'])
        for name,sha in receipt['files'].items():
            self.assertEqual(hashlib.sha256((self.output/name).read_bytes()).hexdigest(),sha)
        moved=self.root/'新目录'; self.output.rename(moved); self.output=moved
        for tool in ('rsi_wiki.py','rsi_review.py','import_rsi_case.py','report_rsi_tdd.py'):
            self.cli(tool,'--help')
        self.assertNotIn(str(ROOT),(self.output/'DELIVERY_MANIFEST.json').read_text())

    def test_empty_selection_does_not_block_or_execute(self):
        self.deliver(); report=self.root/'query.json'
        self.cli('rsi_wiki.py','query','--config',self.output/'wiki.json','--question','new task','--output',report)
        data=json.loads(report.read_text()); self.assertEqual(data['matches'],[])
        self.assertFalse(data['no_match_blocks_task']); self.assertFalse(data['commands_executed'])

    def test_new_question_query_decision_keeps_sources_and_limits_after_move(self):
        self.knowledge(); self.deliver(); shutil.rmtree(self.materials)
        report=self.root/'query.json'
        self.cli('rsi_wiki.py','query','--config',self.output/'wiki.json','--question','test failure skip summary','--output',report)
        data=json.loads(report.read_text()); row=data['matches'][0]
        self.assertFalse(row['independently_verified']); self.assertTrue(row['limits'])
        decision=self.root/'decision.json'
        decision.write_text(json.dumps([{'collection':'public','id':'test-results','version':'1',
            'sha256':row['entry_sha256'],'action':'NOT_ADOPT','reason':'Need task-specific independent checks'}]))
        dest=self.root/'adoption.json'
        self.cli('rsi_wiki.py','record','--query',report,'--decisions',decision,'--output',dest)
        saved=json.loads(dest.read_text()); self.assertEqual(saved['decisions'][0]['read_snapshot'],row)
        self.cli('rsi_wiki.py','record','--query',report,'--decisions',decision,'--output',dest,ok=False)

    def test_private_unselected_materials_are_not_delivered(self):
        (self.materials/'private.json').write_text('PRIVATE EXPECTATION')
        self.deliver()
        self.assertFalse((self.output/'private.json').exists())
        self.assertFalse(any(b'PRIVATE EXPECTATION' in p.read_bytes() for p in self.output.rglob('*') if p.is_file()))

    def test_missing_file_and_escaping_path_fail_before_output(self):
        for value in ('knowledge/missing.txt','../private.txt','/private.txt'):
            self.manifest['knowledge_files']=[value]
            with self.assertRaises((ValueError,OSError)): self.deliver()
            self.assertFalse(self.output.exists())

    def test_existing_output_and_aliased_source_escape_preserve_old_bytes(self):
        self.deliver(); old=(self.output/'DELIVERY_MANIFEST.json').read_bytes()
        with self.assertRaises(FileExistsError): self.deliver()
        self.assertEqual((self.output/'DELIVERY_MANIFEST.json').read_bytes(),old)
        self.output=self.root/'new'; (self.materials/'knowledge').symlink_to(self.root)
        (self.root/'outside.txt').write_text('outside')
        self.manifest['knowledge_files']=['knowledge/outside.txt']
        with self.assertRaises(ValueError): self.deliver()
        self.assertFalse(self.output.exists())

    def test_knowledge_binding_mismatch_missing_entry_and_duplicate_rejected(self):
        self.knowledge()
        for mutation in ('version','entry','duplicate'):
            original=json.loads(json.dumps(self.manifest))
            if mutation=='version': self.manifest['wiki']['collections'][0]['version']='2'
            elif mutation=='entry': self.manifest['knowledge_files'].remove('knowledge/public/entry.json')
            else: self.manifest['knowledge_files'].append('knowledge/public/source.txt')
            with self.assertRaises(ValueError): self.deliver()
            self.assertFalse(self.output.exists()); self.manifest=original

    def test_reviewer_prepare_plan_and_protected_report_checker_use_delivered_code(self):
        self.deliver(); fixture=review_fixtures.RSIReviewTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        manifest=fixture.root/'manifest.json'; manifest.write_text(json.dumps(fixture.manifest))
        request=self.root/'request.json'
        self.cli('rsi_review.py','--output',request,'prepare','--manifest',manifest)
        r=json.loads(request.read_text()); proposal=self.root/'proposal.json'
        self.cli('rsi_review.py','--output',proposal,'plan','--request',request,'--program-id','DELIVERY-REVIEW')
        self.assertFalse(json.loads(proposal.read_text())['runtime_authorized'])
        report=self.root/'review.json'; report.write_text(json.dumps(review_fixtures.report_fixture(r)))
        protected=self.root/'protected'; protected.mkdir()
        shutil.copyfile(self.output/'src/harness_foundry_factory/rsi_review.py',protected/'checker.py')
        result=subprocess.run([sys.executable,'-I','-S','-B',str(protected/'checker.py'),'--request',str(request),'--report',str(report)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        wrong=review_fixtures.report_fixture(r);wrong['request_sha256']='0'*64;report.write_text(json.dumps(wrong))
        result=subprocess.run([sys.executable,'-I','-S','-B',str(protected/'checker.py'),'--request',str(request),'--report',str(report)],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)

    def test_tdd_cli_preserves_development_pair_and_independent_boundary(self):
        self.deliver(); fixture=tdd_fixtures.RSITddTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        case=self.root/'case.json';case.write_text(json.dumps(fixture.case))
        assoc=self.root/'association.json';assoc.write_text(json.dumps(fixture.association))
        report=self.root/'tdd.json'
        self.cli('report_rsi_tdd.py','--case',case,'--association',assoc,'--output',report)
        data=json.loads(report.read_text());self.assertFalse(data['full_tdd_verified'])
        self.assertFalse(data['acceptance_verified'])
        self.assertEqual(data, __import__('harness_foundry_factory.rsi_tdd',fromlist=['associate_tdd']).associate_tdd(fixture.case,fixture.association))

    def test_runtime_package_includes_entrypoints_and_prepares_same_delivery(self):
        spec=importlib.util.spec_from_file_location('rsi_generic',ROOT/'devtools/package_generic_release.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        files=module.collect_files(ROOT); package=self.root/'package';package.mkdir()
        for name,raw in files.items():
            p=package/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        selection=self.materials/'selection.json';selection.write_text(json.dumps(self.manifest))
        result=subprocess.run([sys.executable,'-I','-S','-B',str(package/'tools/prepare_rsi_delivery.py'),
            '--manifest',str(selection),'--output',str(self.output)],cwd=self.root,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue((self.output/'docs/RSI_DELIVERY.md').is_file())
        self.assertIn('RSI_DELIVERY.md',files['.agents/skills/harness-foundry-build/SKILL.md'].decode())
        for name in ('src/harness_foundry_factory/rsi_cases.py','tools/rsi_wiki.py'):
            self.assertEqual((self.output/name).read_bytes(),files[name])
        self.cli('rsi_review.py','--help')

    def test_delivered_retrieval_twice_keeps_original_budget_and_database(self):
        self.deliver(); fixture=review_fixtures.RSIReviewControllerTests(); fixture.setUp()
        self.addCleanup(fixture.doCleanups); f=fixture.f
        f.prepare(); result=f.controller().advance(f.prepared_id,advance_mode='ONE_ATTEMPT')
        self.assertEqual(result['attempt_status'],'ACCEPTED')
        attempt=f.events('BUILD_ATTEMPT_STARTED')[0]['payload']['attempt_id']
        request=self.root/'request.json';request.write_text(json.dumps(fixture.request))
        before=f.events(); receipts=[]
        for n in range(2):
            out=self.root/('receipt-'+str(n)+'.json')
            self.cli('rsi_review.py','--output',out,'retrieve','--request',request,
                '--report',f.workspace/'outputs/review.json','--database',f.store.database_path,
                '--program-id',f.program,'--prepared-id',f.prepared_id,'--attempt-id',attempt,'--objective-status','FAIL')
            receipts.append(json.loads(out.read_text()))
        self.assertEqual(receipts[0],receipts[1]);self.assertEqual(f.events(),before)
        self.assertEqual(receipts[0]['budget']['attempts_consumed'],1)
        self.assertEqual(receipts[0]['new_model_calls'],0);self.assertEqual(len(fixture.calls),1)

    def test_delivered_tdd_inapplicable_does_not_require_red(self):
        self.deliver(); fixture=tdd_fixtures.RSITddTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.cycle['applicability']='NOT_APPLICABLE'
        fixture.cycle['reason']='Document-only task, no selected executable behavior'
        fixture.cycle.pop('red');fixture.cycle.pop('green')
        case=self.root/'case.json';case.write_text(json.dumps(fixture.case))
        assoc=self.root/'assoc.json';assoc.write_text(json.dumps(fixture.association))
        self.cli('report_rsi_tdd.py','--case',case,'--association',assoc,'--output',self.root/'tdd.json')

    def test_delivered_collector_runs_real_red_green_without_development_imports(self):
        self.deliver();project=self.root/'project';project.mkdir();scratch=self.root/'scratch';scratch.mkdir()
        (project/'test_total.py').write_text('import unittest\nfrom total import total\nclass Total(unittest.TestCase):\n def test_total(self): self.assertEqual(total([4,-1]),3)\n')
        implementation=project/'total.py';implementation.write_text('def total(xs): return 0\n')
        argv=[sys.executable,'-I','-S','-B',str(self.output/'src/harness_foundry_factory/test_execution.py'),
              '--project',str(project),'--workdir',str(scratch),'--python',sys.executable]
        red=subprocess.run(argv,cwd=self.root,capture_output=True,text=True,timeout=30)
        self.assertEqual(red.returncode,1,red.stderr);r=json.loads(red.stdout)
        self.assertEqual(r['failures'][0]['test'],'test_total.Total.test_total');self.assertTrue(r['protected_source_unchanged'])
        original=(project/'test_total.py').read_bytes()
        implementation.write_text('def total(xs): return sum(xs)\n')
        green=subprocess.run(argv,cwd=self.root,capture_output=True,text=True,timeout=30)
        self.assertEqual(green.returncode,0,green.stderr);g=json.loads(green.stdout)
        self.assertEqual(g['successes'],['test_total.Total.test_total']);self.assertEqual((project/'test_total.py').read_bytes(),original)
        self.assertEqual(r['status'],'CHECKS_FAILED');self.assertEqual(g['status'],'CHECKS_PASS')
