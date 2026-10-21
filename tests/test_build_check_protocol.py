"""Protocol delivery uses actual task context and does not change authority."""

from copy import deepcopy
import json
import unittest

from harness_foundry_factory.build_check_protocol import verification_interfaces
from harness_foundry_factory.build_runtime import classify_verification_result
import test_build_runtime as support
import test_build_resources as resources


class CheckProtocolTests(unittest.TestCase):
    def fixture(self, mode='pass'):
        owner=resources.BuildResourceIntegrationTests()
        f=owner.fixture(mode)
        self.addCleanup(owner.doCleanups)
        return f

    def test_actual_invocation_has_per_case_protocol_and_unchanged_authority(self):
        f=self.fixture()
        f.plan['workpacks'][0]['verification'][1].pop('resource_profile_ref')
        f.prepare()
        controller=f.controller();_,prepared,_=controller._current(f.prepared_id)
        events=deepcopy(f.events())
        inv=controller._invocation(prepared,f.plan['workpacks'][0],f.plan['workpacks'][0]['local_argv'])
        context=json.loads(inv['prompt'].split('\n',1)[1])['task']
        interfaces=context['verification_interfaces']
        self.assertEqual([i['case_id'] for i in interfaces],['READ-ROWS','REJECT-MALFORMED'])
        self.assertEqual(interfaces[0]['required_checks'],['temp','sqlite'])
        self.assertEqual(interfaces[0]['summary_environment'],'FOUNDRY_REPORT_DIR/summary.json')
        self.assertEqual(interfaces[1]['result_protocol'],'EXISTING_NON_RESOURCE_INTERFACE')
        self.assertEqual(inv['scope'],prepared['scope'])
        self.assertEqual(inv['write_roots'],[str(f.workspace/'src')])
        self.assertEqual(f.events(),events)
        self.assertEqual(f.runner.invocations,[])

    def test_projection_excludes_oracle_credential_and_unrelated_profile(self):
        f=self.fixture()
        scope=deepcopy(f.scope)
        p=scope['verification_resources']['profiles']['local']
        p['credentials']={'TOKEN':{'ref':'PRIVATE_CREDENTIAL_REF','purpose':'private'}}
        scope['verification_resources']['checker_files']=['PRIVATE_EXPECTED.json']
        scope['verification_resources']['profiles']['UNUSED']={**p,'required_checks':['UNRELATED']}
        projected=json.dumps(verification_interfaces(f.plan['workpacks'][0],scope))
        for private in ('PRIVATE_CREDENTIAL_REF','PRIVATE_EXPECTED','UNRELATED','UNUSED',str(f.verifier),str(f.root)):
            self.assertNotIn(private,projected)

    def test_local_and_remote_existing_additional_obligations_are_delivered(self):
        for mode,key in [('local-service','services_stopped'),('remote-service','external_effects')]:
            with self.subTest(mode=mode):
                f=self.fixture(mode)
                row=verification_interfaces(f.plan['workpacks'][0],f.scope)[0]
                self.assertIn(key,row['additional_report_fields'])

    def test_legacy_success_does_not_acquire_json_requirement(self):
        result={'status':'PASS','exit_code':0,'stdout':'ordinary existing checker output'}
        self.assertEqual(classify_verification_result(result),result)
        f=support.BuildRuntimeTests();f.setUp();self.addCleanup(f.doCleanups)
        rows=verification_interfaces(f.plan['workpacks'][0],f.scope)
        self.assertTrue(all(r['result_protocol']=='EXISTING_NON_RESOURCE_INTERFACE' for r in rows))


if __name__=='__main__':unittest.main()
