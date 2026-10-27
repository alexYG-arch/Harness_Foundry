"""Optional compact storage in isolated databases; no active-library migration."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from harness_foundry_factory import revision_bodies as bodies
from harness_foundry_factory.build_entrypoint import apply_build_request, read_build
from harness_foundry_factory.build_types import RequestValidationError, IdempotencyConflictError, RevisionConflictError
from harness_foundry_factory.revision_store import RevisionControlEventStore as Store
import test_build_runtime as support
import test_build_rebind as rebind
import test_build_preview as preview
import test_build_correction_runtime as correction


class CompactStoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'compact.sqlite3'
        self.store = Store(self.path, physical_format=bodies.COMPACT)

    def entries(self, text='line\r\n汉🙂\n', *, source_id='S1', extra=None):
        return [{'event_type': 'BUILD_SOURCES_CAPTURED', 'payload': {'snapshot': {'sources': [
            {'source_id': source_id, 'path_or_uri': source_id + '.md', 'text': text,
             'format': 'MARKDOWN', 'loaded_completely': True, 'line_count': 2}]},
             'extra': extra or {}}}]

    def append(self, entries=None, revision=0, key='one', program='P', **kwargs):
        return self.store.append_batch(program, self.entries() if entries is None else entries,
            expected_revision=revision, idempotency_key=key, created_at=support.NOW, **kwargs)

    def counts(self):
        with closing(sqlite3.connect(self.path)) as c:
            return tuple(c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]
                         for table in ('control_source_bodies','control_events','control_idempotency'))

    def test_same_body_keeps_distinct_sources_events_and_programs(self):
        a=self.append(); b=self.append(self.entries(source_id='S2'),1,'two')
        q=self.append(program='Q'); self.assertEqual(self.counts(),(1,3,3))
        self.assertEqual(self.store.list_events('P'),a+b)
        self.assertEqual(self.store.list_events('Q'),q)
        self.assertEqual(Store(self.path,read_only=True).physical_format,bodies.COMPACT)
        self.assertIsNone(self.store.find_event('Q',event_type='BUILD_SOURCES_CAPTURED',event_id=a[0]['event_id']))

    def test_exact_types_line_endings_and_original_order_are_preserved(self):
        entries=self.entries(extra={'number':1,'boolean':True,'float':1.0,'literal':{'body_id':'data','path':['text']}})
        entries+= [{'event_type':'RESULT','payload':{'failed':False,'count':0}}]
        first=self.append(entries); self.append(self.entries('other'),2,'later')
        for _ in range(2):
            self.assertEqual(self.store.idempotent_events('P','one'),first)
            self.assertEqual(self.append(entries),first)
        for value in (True,1.0,2):
            changed=deepcopy(entries);changed[0]['payload']['extra']['number']=value
            with self.assertRaises(IdempotencyConflictError):self.append(changed)
        with self.assertRaises(IdempotencyConflictError):self.append(self.entries('line\n汉🙂\n'))
        self.assertEqual(self.counts(),(2,3,2))
        self.assertEqual(self.store.list_events('P')[0]['payload'],entries[0]['payload'])

    def test_payload_and_idempotency_do_not_repeat_body(self):
        text='UNIQUE-BODY'*10000; result=self.append(self.entries(text))
        with closing(sqlite3.connect(self.path)) as c:
            event=c.execute('SELECT payload_json, source_refs_json FROM control_events').fetchone()
            request,returned=c.execute('SELECT request_json,events_json FROM control_idempotency').fetchone()
            self.assertNotIn(text[:100],''.join(event)+request+returned)
            self.assertEqual(json.loads(returned),[result[0]['event_id']])
            self.assertEqual(c.execute('SELECT content FROM control_source_bodies').fetchone()[0],text.encode())

    def test_stored_request_restores_all_original_fields_and_json_types(self):
        entries=self.entries(extra={'i':1,'b':True,'f':1.0,'null':None})
        entries+=self.entries(source_id='S2')
        self.append(entries)
        with self.store._connection() as c:
            request=json.loads(c.execute('SELECT request_json FROM control_idempotency').fetchone()[0])
            for entry in request['entries']:
                bodies.hydrate_payload(c,entry['payload'],json.dumps(entry.pop('source_refs')))
        # Compare canonical JSON, since Python equality equates 1/True/1.0.
        self.assertEqual(json.dumps(request,sort_keys=True),json.dumps(
            {'expected_revision':0,'entries':entries},sort_keys=True))

    def test_bad_reference_size_path_or_duplicate_cannot_hydrate(self):
        self.append()
        with self.store._connection() as c:
            row=c.execute('SELECT payload_json,source_refs_json FROM control_events').fetchone()
            refs=json.loads(row['source_refs_json'])
            variants=[([{**refs[0],'size_bytes':1}]),
                      ([{**refs[0],'path':['snapshot','sources',10,'text']}]), refs+refs]
            for invalid in variants:
                with self.subTest(refs=invalid),self.assertRaises(RequestValidationError):
                    bodies.hydrate_payload(c,json.loads(row['payload_json']),json.dumps(invalid))

    def test_metadata_omits_body_and_full_hydration_is_exact(self):
        original=self.append()[0];view=self.store.list_control_events('P')
        with patch('harness_foundry_factory.revision_bodies.verify_body',side_effect=AssertionError('body not needed')):
            self.assertEqual(self.store.event_count('P'),1)
            self.assertEqual(self.store.list_control_events('P'),view)
            metadata=self.store.hydrate_source_event('P',view,original['event_id'],include_text=False)
        self.assertNotIn('text',metadata['payload']['snapshot']['sources'][0])
        self.assertEqual(self.store.hydrate_source_event('P',view,original['event_id']),original)

    def test_inline_payload_in_compact_store_remains_readable(self):
        with patch('harness_foundry_factory.revision_store.encode_payload',side_effect=lambda k,p:(deepcopy(p),[],{})):
            inline=self.append()
        compact=self.append(self.entries('different'),1,'next')
        self.assertEqual(self.store.list_events('P'),inline+compact)
        self.assertEqual(self.store.idempotent_events('P','one'),inline)

    def test_cas_require_new_and_concurrency_add_no_orphan_bodies(self):
        self.append()
        with self.assertRaises(RevisionConflictError):self.append(require_new=True)
        with self.assertRaises(RevisionConflictError):self.append(self.entries('orphan'),0,'stale')
        def racing(_):return self.append(self.entries('next'),1,'shared')
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(racing,range(2)))
        self.assertEqual(results[0],results[1]);self.assertEqual(self.counts(),(2,2,2))

    def test_failed_event_and_process_crash_roll_back_body_and_request(self):
        with patch('harness_foundry_factory.revision_store.uuid.uuid4') as uid:
            uid.return_value.hex='duplicate'
            with self.assertRaises(sqlite3.IntegrityError):self.append(self.entries()+self.entries('other'))
        self.assertEqual(self.counts(),(0,0,0))
        script='''import os,sys
from harness_foundry_factory.revision_store import RevisionControlEventStore
from harness_foundry_factory import revision_store
s=RevisionControlEventStore(sys.argv[1]); original=revision_store.store_bodies
def stop(c,b):
 original(c,b); os._exit(73)
revision_store.store_bodies=stop
s.append_batch('P',[{'event_type':'BUILD_SOURCES_CAPTURED','payload':{'snapshot':{'sources':[{'text':'crash'}]}}}],expected_revision=0,idempotency_key='crash',created_at='now')
'''
        result=subprocess.run([sys.executable,'-B','-c',script,str(self.path)],capture_output=True,timeout=10)
        self.assertEqual(result.returncode,73,result.stderr.decode());self.assertEqual(self.counts(),(0,0,0))
        self.append();self.assertEqual(self.counts(),(1,1,1))

    def test_body_guards_and_schema_mismatch_preserve_old_database(self):
        self.append()
        with closing(sqlite3.connect(self.path)) as c:
            for sql in ('UPDATE control_source_bodies SET content=x\'00\'','DELETE FROM control_source_bodies'):
                with self.assertRaises(sqlite3.IntegrityError):c.execute(sql)
            with self.assertRaises(RequestValidationError):Store._require_exact_existing_schema(c)
        before=self.path.read_bytes()
        for ro in (False,True):
            with self.assertRaises(RequestValidationError):Store(self.path,read_only=ro,physical_format=bodies.INLINE)
        self.assertEqual(before,self.path.read_bytes())
        old=self.path.parent/'old.sqlite3';Store(old);before=old.read_bytes()
        with self.assertRaises(RequestValidationError):Store(old,physical_format=bodies.COMPACT)
        self.assertEqual(before,old.read_bytes());self.assertEqual(Store(old).physical_format,bodies.INLINE)

    def test_missing_or_damaged_body_retains_known_control_facts_and_can_be_restored(self):
        expected=self.append();self.append([{'event_type':'KNOWN_RESULT','payload':{'status':'FAIL'}}],1,'fail')
        with closing(sqlite3.connect(self.path)) as c:
            original=c.execute('SELECT body_id,size_bytes,content FROM control_source_bodies').fetchone()
            c.execute('DROP TRIGGER control_source_bodies_reject_delete');c.execute('DELETE FROM control_source_bodies')
            c.execute(bodies.BODY_TRIGGERS['control_source_bodies_reject_delete']);c.commit()
        self.assertEqual(self.store.list_control_events('P')[-1]['payload']['status'],'FAIL')
        with self.assertRaises(RequestValidationError):self.store.list_events('P')
        with self.assertRaises(RequestValidationError):self.store.idempotent_events('P','one')
        # Corrupt only a disposable fixture; original byte restoration is not production migration.
        with closing(sqlite3.connect(self.path)) as c:
            c.execute('INSERT INTO control_source_bodies VALUES (?,?,?)',(original[0],original[1],b'bad'));c.commit()
        with self.assertRaises(RequestValidationError):self.store.list_events('P')
        with closing(sqlite3.connect(self.path)) as c:
            c.execute('DROP TRIGGER control_source_bodies_reject_update')
            c.execute('UPDATE control_source_bodies SET content=?',(original[2],))
            c.execute(bodies.BODY_TRIGGERS['control_source_bodies_reject_update']);c.commit()
        self.assertEqual(self.store.idempotent_events('P','one'),expected);self.assertEqual(self.counts(),(1,2,2))

    def test_identity_collision_compares_real_bytes(self):
        with patch('harness_foundry_factory.revision_bodies.content_id',return_value='collision'):
            self.append(self.entries('same'))
            with self.assertRaises(RequestValidationError):self.append(self.entries('diff'),1,'different')
            with self.assertRaises(RequestValidationError):self.append(self.entries('diff'))
        self.assertEqual(self.counts(),(1,1,1))

    def test_public_record_selects_format_without_new_execution_authority(self):
        f=support.BuildRuntimeTests();f.setUp();self.addCleanup(f.doCleanups)
        path=f.root/'public.sqlite3';request={**f.request,'physical_format':bodies.COMPACT,
            'expected_revision':0,'idempotency_key':'proposal'}
        apply_build_request('record-build-plan',request,path)
        result=read_build(path,f.program)
        self.assertEqual(result['physical_format'],bodies.COMPACT);self.assertEqual(result['attempts'],[])
        self.assertEqual(result['authorizations'],[])
        self.assertEqual(Store(path,read_only=True).event_count(f.program),1)
        before=path.read_bytes()
        with self.assertRaises(RequestValidationError):apply_build_request('record-build-plan',{**request,'physical_format':bodies.INLINE},path)
        self.assertEqual(before,path.read_bytes())

    def test_compact_initialization_failure_does_not_leave_partial_schema(self):
        path=self.path.parent/'interrupted.sqlite3';original=bodies.initialize_schema
        def fail(c):original(c);raise RuntimeError('injected DDL interruption')
        with patch('harness_foundry_factory.revision_store.initialize_body_schema',side_effect=fail),self.assertRaises(RuntimeError):
            Store(path,physical_format=bodies.COMPACT)
        with closing(sqlite3.connect(path)) as c:
            self.assertEqual(c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),[])


class CompactRebindTests(rebind.RebindTests):
    """Reuse existing assertions on actual compact storage; no new business cases."""
    def setUp(self):
        with patch.object(support,'ControlEventStore',side_effect=lambda p,**kw:Store(p,**kw,physical_format=bodies.COMPACT)):
            super().setUp()


class CompactPreviewTests(preview.BuildPreviewTests):
    def setUp(self):
        # Keep the inherited assertions unchanged while selecting compact
        # storage for both the support controller and empty native fixture.
        factory = lambda p, **kw: Store(p, **{**kw, 'physical_format': bodies.COMPACT})
        fixture_patch = patch.object(preview, 'RevisionControlEventStore', side_effect=factory)
        fixture_patch.start(); self.addCleanup(fixture_patch.stop)
        with patch.object(support, 'ControlEventStore', side_effect=factory):
            super().setUp()
        self.request['physical_format']=bodies.COMPACT

    def test_preview_and_capture_share_one_body_and_original_envelope(self):
        request=self.confirm();result=self.materialize(request);rows=self.events()
        with closing(sqlite3.connect(self.db)) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM control_source_bodies').fetchone()[0],1)
        self.assertEqual(rows[0]['payload']['preview']['sha256'],request['preview_sha256'])
        self.assertEqual(self.materialize(request),result)


class CompactCorrectionTests(correction.CorrectionRuntimeTests):
    def setUp(self):
        with patch.object(support,'ControlEventStore',side_effect=lambda p,**kw:Store(p,**kw,physical_format=bodies.COMPACT)):
            super().setUp()
