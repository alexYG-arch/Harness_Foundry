"""New delivery planning uses the existing apply/effects/merge contracts."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from tests import test_capability_feature_inventory as fi
from tests import test_harness_composition_helpers as ch
from harness_foundry_factory.build_effects import snapshot_effects, compare_effects

INTENTS=fi.module('delivery_intents'); STACK=fi.module('stack_handoff')


class DeliveryIntentTests(unittest.TestCase):
    setUp=fi.FeatureInventoryTests.setUp
    write=fi.FeatureInventoryTests.write
    config=fi.FeatureInventoryTests.config

    def test_real_apply_declares_result_and_reread_does_not_replay(self):
        m,_=fi.P.build_materials(self.config(),self.root/'prep')
        payload=self.root/'payload';STACK.public_delivery(m,payload)
        prep=self.root/'intents';fragment=INTENTS.prepare(payload,prep,result='reports/apply.json')
        target=self.root/'target';target.mkdir();contract=fragment['effects']
        before=snapshot_effects(target,['harness','reports'],contract)
        apply=ch.load_helper('apply')
        with patch('builtins.print'):first=apply.apply(prep/'apply-intents.json',target,fragment['result'])
        after=snapshot_effects(target,['harness','reports'],contract)
        self.assertEqual(compare_effects(before,after,contract)['status'],'PASS')
        before_files={p:p.stat().st_mtime_ns for p in (target/'harness').rglob('*') if p.is_file()}
        # A fresh allowed invocation is idempotent, while merely reading reports invokes nothing.
        with patch('builtins.print'):second=apply.apply(prep/'apply-intents.json',target,fragment['result'])
        self.assertTrue(all(r['status']=='ALREADY_DESIRED' for r in second['files']))
        self.assertEqual(before_files,{p:p.stat().st_mtime_ns for p in before_files})
        with patch.object(apply,'apply',side_effect=AssertionError('retrieval must not execute')):
            self.assertEqual(json.loads((target/'reports/apply.json').read_text())['status'],'APPLIED')
        (target/'harness/unplanned.txt').write_text('outside declaration')
        self.assertEqual(compare_effects(after,snapshot_effects(target,['harness','reports'],contract),contract)['status'],'VIOLATION')

    def test_link_is_separate_layout_step_not_required_file(self):
        payload=self.root/'payload';payload.mkdir();(payload/'real').write_text('content');(payload/'alias').symlink_to('real')
        fragment=INTENTS.prepare(payload,self.root/'prep',result='reports/result.json')
        self.assertTrue(fragment['links_require_layout_writer'])
        self.assertNotIn('harness/capabilities/alias',fragment['effects']['required'])
        with self.assertRaises(ValueError):INTENTS.prepare(payload,self.root/'invalid',result='harness/capabilities/result.json')


class ConsecutiveGeneratedBaselineTests(unittest.TestCase):
    setUp=ch.CompositionHelperTests.setUp
    payload=ch.CompositionHelperTests.payload
    manifest=ch.CompositionHelperTests.manifest
    def test_two_upgrades_keep_generated_and_custom_versions_separate(self):
        g=self.payload('g0',b'default');c=self.payload('c0',b'user custom')
        # Each unchanged new generation keeps C. The next G is N, never the merge result.
        for index in (1,2):
            n=self.payload('n'+str(index),b'default')
            source=self.manifest('merge'+str(index)+'.json',[{'path':'settings.txt','G':g,'C':c,'N':n}])
            out=self.root/('round'+str(index));result=self.merge.merge(source,out)
            self.assertEqual(result['status'],'READY');row=result['files'][0]
            self.assertEqual((out/row['resolved']['file']).read_bytes(),b'user custom')
            self.assertEqual((out/row['inputs']['N']['file']).read_bytes(),b'default')
            g=n;c=self.payload('c'+str(index), (out/row['resolved']['file']).read_bytes())
        changed=self.payload('n3',b'new default')
        result=self.merge.merge(self.manifest('conflict.json',[{'path':'settings.txt','G':g,'C':c,'N':changed}]),self.root/'conflict')
        self.assertEqual(result['files'][0]['status'],'CONFLICT')
