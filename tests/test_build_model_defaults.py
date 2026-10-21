"""Prepared model selection and dispatch bindings; fixture receivers, no model calls."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

import test_build_runtime as support
from harness_foundry_factory.build_runtime import prepare_build_authorization, BuildController, NativeBuildRunner
from harness_foundry_factory.build_entrypoint import read_build, apply_build_request
from harness_foundry_factory.build_types import RequestValidationError, IdempotencyConflictError


class BuildModelDefaultsTests(unittest.TestCase):
    def setUp(self):
        self.f = support.BuildRuntimeTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.calls = []
        self.f.runner = self.f._codex_fixture_runner(self.calls)
        self.f.prepare(approve=False)
        self.selected = {'model': 'fixture-model', 'model_reasoning_effort': 'fixture-effort',
                         'model_defaults_source': {'method': 'CODEX_CONFIG_READ', 'codex_executable': '/usr/bin/true'}}

    def prepare_defaults(self, **extra):
        f=self.f; scope=deepcopy(f.scope); scope['model']=None
        arguments={**f.kwargs('follow-defaults'), **extra}
        with patch('harness_foundry_factory.coding_defaults.resolve_codex_defaults', return_value=self.selected) as resolver:
            event=prepare_build_authorization(f.store,f.program,f.proposal_id,f.source_id,scope,
                                             follow_codex_defaults=True,**arguments)
        return event, resolver, scope, arguments

    def test_selection_is_frozen_readable_and_idempotent_before_any_approval(self):
        f=self.f; event,resolver,scope,args=self.prepare_defaults()
        resolver.assert_called_once_with(f.scope['codex_executable'])
        self.assertIsNone(scope['model'])
        self.assertEqual(event['payload']['scope']['model_reasoning_effort'],'fixture-effort')
        read=read_build(f.store.database_path,f.program)['authorizations'][-1]
        self.assertEqual(read['model_defaults_source'],self.selected['model_defaults_source'])
        self.assertFalse(f.events('BUILD_ATTEMPT_STARTED'))
        with patch('harness_foundry_factory.coding_defaults.resolve_codex_defaults',side_effect=AssertionError('must not refresh defaults')):
            repeated=prepare_build_authorization(f.store,f.program,f.proposal_id,f.source_id,scope,
                                                follow_codex_defaults=True,**args)
        self.assertEqual(repeated,event)
        with self.assertRaises(IdempotencyConflictError):
            prepare_build_authorization(f.store,f.program,f.proposal_id,f.source_id,{**scope,'model':'different'},
                                        follow_codex_defaults=True,**args)

    def test_public_prepare_and_authorized_prompt_use_frozen_pair(self):
        f=self.f; scope={**f.scope,'model':None}
        request={'program_id':f.program,'proposal_event_id':f.proposal_id,'source_event_id':f.source_id,
                 'scope':scope,'follow_codex_defaults':True,'expected_revision':len(f.events()),'idempotency_key':'public-defaults'}
        # Public adapter's wall clock is real; fixture expiry is moved forward without dispatch.
        request['scope']['expires_at']='2099-01-01T00:00:00Z'
        with patch('harness_foundry_factory.coding_defaults.resolve_codex_defaults',return_value=self.selected):
            event=apply_build_request('prepare-build-authorization',request,f.store.database_path)
        f.prepared_id=event['event_id']
        from harness_foundry_factory.build_runtime import approve_build_authorization
        from datetime import datetime,timezone
        approve_build_authorization(f.store,f.program,f.prepared_id,human_message_ref='TEST ONLY',
            expected_revision=len(f.events()),idempotency_key='approve-defaults',created_at=datetime.now(timezone.utc).isoformat())
        controller=f.controller(); _,prepared,plan=controller._current(f.prepared_id)
        invocation=controller._invocation(prepared,plan['workpacks'][0],[])
        authority=json.loads(invocation['prompt'].split('\n',1)[1])['task']['runtime_authorization']
        self.assertEqual(authority['model'],'fixture-model'); self.assertEqual(authority['model_reasoning_effort'],'fixture-effort')
        with patch('harness_foundry_factory.coding_process.CodexCodingRunner.run',return_value={'status':'MODEL_PROCESS_FAILED'}) as run:
            NativeBuildRunner()(invocation,lambda:None)
        command=run.call_args.args[0]
        self.assertEqual(command.model,'fixture-model'); self.assertEqual(command.reasoning_effort,'fixture-effort')
        self.assertFalse(f.events('BUILD_ATTEMPT_STARTED'))

    def test_explicit_selection_does_not_resolve_global_defaults(self):
        f=self.f
        with patch('harness_foundry_factory.coding_defaults.resolve_codex_defaults',side_effect=AssertionError('unexpected native lookup')):
            event=prepare_build_authorization(f.store,f.program,f.proposal_id,f.source_id,
                    {**f.scope,'model_reasoning_effort':'high'},**f.kwargs('explicit'))
        self.assertNotIn('model_defaults_source',event['payload'])
        self.assertEqual(event['payload']['scope']['model'],f.scope['model'])

    def test_conflicting_selection_and_nonboolean_switch_rejected(self):
        f=self.f
        for scope,follow in ((f.scope,True),({**f.scope,'model':None,'model_reasoning_effort':'high'},True),(f.scope,'true')):
            with self.subTest(scope=scope,follow=follow),self.assertRaises(RequestValidationError):
                prepare_build_authorization(f.store,f.program,f.proposal_id,f.source_id,scope,
                    follow_codex_defaults=follow,**f.kwargs('bad-defaults'))
        self.assertFalse(f.events('BUILD_ATTEMPT_STARTED'))

    def test_frozen_defaults_continue_without_resolving_again(self):
        f=self.f; event,_,_,_=self.prepare_defaults(); f.prepared_id=event['event_id']; f.approve()
        with patch('harness_foundry_factory.coding_defaults.resolve_codex_defaults',side_effect=AssertionError('unexpected re-resolution')):
            first=f.controller().advance(f.prepared_id,advance_mode='ONE_ATTEMPT')
            again=f.controller().advance(f.prepared_id,advance_mode='ONE_ATTEMPT')
        self.assertEqual(first['attempt_status'],'ACCEPTED')
        self.assertEqual(again['attempt_status'],'ACCEPTED')
        self.assertEqual(len(self.calls),1)
        self.assertEqual(len(f.events('BUILD_ATTEMPT_STARTED')),2)

if __name__=='__main__': unittest.main()
