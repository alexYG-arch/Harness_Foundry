from copy import deepcopy
import json
import hashlib
from pathlib import Path
import shutil
import unittest
from tests import test_capability_feature_inventory as fi
S=fi.module('stack_handoff');CHECK=fi.module('check_capability_delivery');R=fi.module('report_delivery')

class FeatureReportsTests(unittest.TestCase):
    setUp=fi.FeatureInventoryTests.setUp
    write=fi.FeatureInventoryTests.write
    config=fi.FeatureInventoryTests.config
    def delivery(self):
        materials,_=fi.P.build_materials(self.config(),self.root/'prep')
        self.target=self.root/'delivered';manifest=S.public_delivery(materials,self.target)
        self.expected=self.root/'protected';shutil.copytree(self.target,self.expected)
        self.instructions=self.root/'AGENTS.md';self.instructions.write_text('Read kit/2/target.md and use offline.\n')
        return manifest
    def test_protected_manifest_and_reference_checks(self):
        self.delivery();r=CHECK.check(self.target,self.expected,[self.instructions]);self.assertEqual(r['status'],'CHECKS_PASS')
        (self.target/'kit/2/shared.py').write_text('broken')
        self.assertEqual(CHECK.check(self.target,self.expected,[self.instructions])['status'],'CHECKS_FAILED')
    def test_unknown_file_and_missing_reference_rejected(self):
        self.delivery();(self.target/'kit/2/extra.py').write_text('unselected')
        self.instructions.write_text('No reference')
        r=CHECK.check(self.target,self.expected,[self.instructions]);self.assertEqual(r['status'],'CHECKS_FAILED')
        self.assertFalse(r['behavior_verified'])
    def test_instruction_reference_resolves_to_actual_delivered_path(self):
        manifest=self.delivery()
        self.assertEqual(manifest['instruction_snippets'],{'kit':'kit/2/target.md'})
        self.instructions.write_text('Read target.md and use offline')
        self.assertEqual(CHECK.check(self.target,self.expected,[self.instructions])['status'],'CHECKS_FAILED')
    def test_legitimate_retained_file_is_checked_without_new_feature_credit(self):
        manifest=self.delivery();(self.target/'user-note.txt').write_text('user customization')
        row={'path':'user-note.txt','sha256':hashlib.sha256((self.target/'user-note.txt').read_bytes()).hexdigest(),
             'owner':'project','decision_ref':'fixture-retain-decision'}
        manifest['retained_unmanaged']=[row]
        for root in (self.target,self.expected):(root/'delivery.json').write_text(json.dumps(manifest))
        self.assertEqual(CHECK.check(self.target,self.expected,[self.instructions])['status'],'CHECKS_PASS')
        self.assertEqual(len(R.report(manifest,[])['features']),2)
        (self.target/'user-note.txt').write_text('changed')
        self.assertEqual(CHECK.check(self.target,self.expected,[self.instructions])['status'],'CHECKS_FAILED')
    def test_old_pass_skip_and_latest_fail_preserved_without_replay(self):
        m=self.delivery();key='kit@2:local';passing={'feature':key,'delivery_sha256':R.identity(m),'status':'PASS','structure':'PASS','behavior':'PASS',
          **{k:'fixture' for k in ('input_ref','expected_ref','checker_ref','environment_ref','report_ref','command_ref','attempt_ref')}}
        receipt=self.root/'check.json';receipt.write_text(json.dumps({'status':'CHECKS_PASS','command_id':'fixture','checks':[{'id':'assertion','status':'PASS'}]}))
        passing['report_ref']={'path':str(receipt),'sha256':hashlib.sha256(receipt.read_bytes()).hexdigest()}
        contexts={key:{k:passing[k] for k in ('input_ref','expected_ref','checker_ref','environment_ref')}}
        self.assertEqual(R.report(m,[passing],contexts)['verified'],1)
        self.assertEqual(R.report(m,[passing])['verified'],0)
        changed=deepcopy(contexts);changed[key]['checker_ref']='new-checker'
        self.assertEqual(R.report(m,[passing],changed)['verified'],0)
        for changed in ({'delivery_sha256':'old'},{'status':'SKIP'},{'status':'FAIL'}):
            evidence=[passing,{**passing,**changed}]
            result=R.report(m,evidence,contexts)
            if 'delivery_sha256' not in changed:self.assertEqual(result['verified'],0)
            self.assertEqual(len(result['features'][0]['evidence']),2);self.assertFalse(result['budget_modified'])
            self.assertEqual(result,R.report(m,evidence,contexts))
        self.assertEqual(R.report(m,[{**passing,'delivery_sha256':'old'}],contexts)['verified'],0)
        receipt.unlink();self.assertEqual(R.report(m,[passing],contexts)['verified'],0)
    def test_workflow_markdown_cannot_claim_no_behavior(self):
        m=self.delivery();m['features'][0]['kind']='workflow';f={'feature':'kit@2:local','delivery_sha256':R.identity(m),'status':'PASS','structure':'PASS','behavior':'NOT_APPLICABLE','behavior_reason':'Markdown','content_and_consumption':'PASS',
          **{k:'fixture' for k in ('input_ref','expected_ref','checker_ref','environment_ref','report_ref')}}
        self.assertEqual(R.report(m,[f])['verified'],0)

class NewVersionTests(unittest.TestCase):
    def test_all_eight_descriptors_and_private_dependencies(self):
        versions={'qt-cmake':'3','python-environment':'2','data-summary':'2','doc-export':'2','host-review':'2','local-dashboard':'5','text-count':'2','reference-notes':'2'}
        for name,version in versions.items():
            with self.subTest(name=name):
                root=fi.BASE/'packages'/name/version;p=json.loads((root/'capability.json').read_text())
                features=fi.I.validate(p)
                self.assertTrue(features)
                for f in features:
                    self.assertTrue(all((root/n).is_file() for n in f['files']))
                private={r for r in p.get('verification_files',[]) if isinstance(r,str)}
                self.assertFalse(private.intersection({n for f in features for n in f['files']}))

if __name__=='__main__':unittest.main()
