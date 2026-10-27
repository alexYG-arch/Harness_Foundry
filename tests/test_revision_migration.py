"""Offline migration in disposable fixtures; never adopt or query a business DB."""
from contextlib import closing
import importlib.util
import json
import errno
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from harness_foundry_factory.revision_store import RevisionControlEventStore as Store
from harness_foundry_factory.revision_bodies import COMPACT, INLINE
from harness_foundry_factory.build_types import canonical_json, IdempotencyConflictError, RequestValidationError
from harness_foundry_factory.build_entrypoint import read_build
from harness_foundry_factory.build_runtime import revoke_build_authorization
from harness_foundry_factory.build_state import project_budget_attempts, attempt_budget
import test_build_runtime as support
import test_build_rebind as rebind
import test_build_correction as correction
import test_build_resources as resources

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('revision_migration', ROOT/'devtools/migrate_revision_store.py')
migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name).resolve();self.db=self.root/'old.sqlite3';self.store=Store(self.db)

    def append(self, text='汉🙂\r\noriginal\n', *, key='one', program='P', extra=None):
        return self.store.append_batch(program,[{'event_type':'BUILD_SOURCES_CAPTURED','payload':{
            'snapshot':{'sources':[{'source_id':key,'path_or_uri':key+'.md','text':text}]},
            'extra':extra or {'bool':True,'integer':1,'float':1.0}}}],
            expected_revision=self.store.event_count(program),idempotency_key=key,created_at='original-time')

    def migrate(self, **kwargs):
        return migration.prepare_migration(self.db,self.root/'converted',**kwargs)

    def test_literal_events_requests_results_and_original_bytes_survive_roundtrip(self):
        first=self.append();self.append(key='two');self.append(program='Q')
        before=self.db.read_bytes();report=self.migrate()
        compact=Store(report['candidate']['path'],read_only=True)
        self.assertEqual(compact.list_events('P'),self.store.list_events('P'))
        for _ in range(2):self.assertEqual(compact.idempotent_events('P','one'),first)
        with compact._connection() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM control_source_bodies').fetchone()[0],1)
        second=migration.prepare_migration(compact.database_path,self.root/'back',target_format=INLINE)
        self.assertEqual(migration.compare_databases(self.db,second['candidate']['path'])['events'],3)
        self.assertEqual(before,self.db.read_bytes());self.assertFalse(report['adoption_authorized'])
        self.assertEqual(report['external_evidence_status'],'REVIEW_REQUIRED')

    def test_converted_exact_append_reuses_old_identity_and_type_difference_conflicts(self):
        original=self.append();report=self.migrate();compact=Store(report['candidate']['path'])
        values=dict(expected_revision=0,idempotency_key='one',created_at='original-time')
        entries=[{'event_type':e['event_type'],'payload':e['payload']} for e in original]
        self.assertEqual(compact.append_batch('P',entries,**values),original)
        entries[0]['payload']['extra']['integer']=True
        with self.assertRaises(IdempotencyConflictError):compact.append_batch('P',entries,**values)
        self.assertEqual(compact.event_count('P'),1)

    def test_wal_committed_pages_are_backed_up_and_uncommitted_work_is_not(self):
        self.append()
        with closing(sqlite3.connect(self.db)) as writer:
            writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute('SELECT COUNT(*) FROM control_events').fetchone()
            self.append('committed WAL',key='two')
            self.assertGreater(self.db.with_name(self.db.name+'-wal').stat().st_size,0)
            writer.execute('BEGIN IMMEDIATE')
            writer.execute("INSERT INTO control_idempotency VALUES ('P','uncommitted','{}','[]','now')")
            report=self.migrate()
            self.assertEqual(report['logical_comparison']['events'],2)
            self.assertEqual(report['logical_comparison']['idempotency_records'],2)
            writer.rollback()
        self.assertEqual(self.store.event_count('P'),2)

    def test_source_growth_is_retained_and_reported_not_silently_adopted(self):
        self.append();original=migration.convert_snapshot
        def grow(*args):
            result=original(*args);self.append('new',key='after-backup');return result
        with patch.object(migration,'convert_snapshot',side_effect=grow):report=self.migrate()
        self.assertTrue(report['source_advanced_since_snapshot'])
        self.assertEqual(report['logical_comparison']['events'],1)
        self.assertEqual(self.store.event_count('P'),2)
        self.assertFalse(report['adoption_authorized'])

    def test_rollback_conversion_includes_new_candidate_events_not_old_snapshot(self):
        self.append();report=self.migrate();self.store=Store(report['candidate']['path'])
        newer=self.append('after hypothetical switch',key='newer')
        rollback=migration.prepare_migration(self.store.database_path,self.root/'rollback',target_format=INLINE)
        result=Store(rollback['candidate']['path'],read_only=True)
        self.assertEqual(result.event_count('P'),2)
        self.assertEqual(result.idempotent_events('P','newer'),newer)
        self.assertEqual(Store(self.db,read_only=True).event_count('P'),1)

    def test_missing_or_changed_external_file_keeps_known_facts_and_original_binding(self):
        self.append();p=self.root/'report.json';p.write_text('{"status":"FAIL"}')
        expected=migration.file_fact(p)
        evidence=[{'path':str(p),'kind':'file','role':'REPORT','expected':expected},
                  {'path':str(self.root/'missing'),'kind':'file','role':'ATTACHMENT'}]
        report=self.migrate(evidence=evidence)
        self.assertEqual([r['status'] for r in report['external_evidence']],['AVAILABLE','UNAVAILABLE'])
        self.assertEqual(report['external_evidence'][0]['declaration']['expected'],expected)
        self.assertEqual(report['external_evidence_status'],'REVIEW_REQUIRED')
        self.assertEqual(json.loads(p.read_text())['status'],'FAIL')
        p.write_text('changed')
        self.assertEqual(migration.evidence_inventory(evidence)[0]['status'],'BOUND_VERSION_CHANGED')
        p.write_text('{"status":"FAIL"}')
        self.assertEqual(migration.evidence_inventory(evidence)[0]['status'],'AVAILABLE')

    def test_declared_tree_paths_spaces_and_links_are_recorded_without_rewriting(self):
        self.append();folder=self.root/'检查 记录';folder.mkdir();(folder/'capture.bin').write_bytes(b'original')
        (folder/'link').symlink_to('capture.bin')
        report=self.migrate(evidence=[{'path':str(folder),'kind':'tree','role':'COMMAND_OBSERVATIONS'}])
        self.assertEqual(report['external_evidence_status'],'DECLARED_FILES_VERIFIED')
        self.assertEqual(report['external_evidence'][0]['files']['link']['link'],'capture.bin')
        self.assertTrue((folder/'link').is_symlink())

    def test_evidence_change_during_conversion_is_not_verified(self):
        self.append();p=self.root/'artifact';p.write_bytes(b'first');original=migration.convert_snapshot
        def change(*args):
            result=original(*args);p.write_bytes(b'changed');return result
        with patch.object(migration,'convert_snapshot',side_effect=change):
            report=self.migrate(evidence=[{'path':str(p),'kind':'file','role':'ACCEPTED_PRODUCT'}])
        self.assertFalse(report['external_evidence_stable']);self.assertEqual(report['external_evidence_status'],'REVIEW_REQUIRED')

    def test_unknown_tables_not_discarded(self):
        self.append()
        with closing(sqlite3.connect(self.db)) as c:c.execute('CREATE TABLE retained (value TEXT)');c.commit()
        before=self.db.read_bytes()
        with self.assertRaises(RequestValidationError):self.migrate()
        self.assertEqual(self.db.read_bytes(),before)
        self.assertEqual(json.loads((self.root/'converted/migration-report.json').read_text())['status'],'INCOMPLETE')

    def test_insufficient_space_and_mid_transaction_failure_preserve_source(self):
        self.append();self.append('second',key='two');before=self.db.read_bytes()
        with patch.object(migration.shutil,'disk_usage',return_value=type('Space',(),{'free':0})()):
            with self.assertRaises(RequestValidationError):self.migrate()
        self.assertEqual(before,self.db.read_bytes())
        original=migration.store_bodies;calls=[]
        def full(c, bodies):
            calls.append(1);original(c,bodies)
            if len(calls)==2:raise sqlite3.OperationalError('database or disk is full')
        with patch.object(migration,'store_bodies',side_effect=full):
            with self.assertRaises(sqlite3.OperationalError):
                migration.prepare_migration(self.db,self.root/'disk-full')
        candidate=Store(self.root/'disk-full/candidate.sqlite3',read_only=True)
        self.assertEqual(candidate.event_count('P'),0)
        with candidate._connection() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM control_source_bodies').fetchone()[0],0)
        self.assertEqual(before,self.db.read_bytes())

    def test_process_interruption_leaves_no_committed_prefix(self):
        self.append();self.append('next',key='two')
        child='''import importlib.util,os,sys
spec=importlib.util.spec_from_file_location('m',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
original=m.store_bodies
def crash(c,b):original(c,b);os._exit(73)
m.store_bodies=crash
m.prepare_migration(sys.argv[2],sys.argv[3])
'''
        p=subprocess.run([sys.executable,'-I','-B','-c',child,str(ROOT/'devtools/migrate_revision_store.py'),str(self.db),str(self.root/'crash')],capture_output=True,timeout=15)
        self.assertEqual(p.returncode,73,p.stderr.decode())
        self.assertFalse((self.root/'crash/migration-report.json').exists())
        self.assertEqual(Store(self.root/'crash/candidate.sqlite3',read_only=True).event_count('P'),0)
        self.assertEqual(self.store.event_count('P'),2)

    def test_public_cli_creates_only_new_candidate_and_retains_source(self):
        self.append();before=self.db.read_bytes()
        p=subprocess.run([sys.executable,'-I','-S','-B',str(ROOT/'devtools/migrate_revision_store.py'),
            '--source',str(self.db),'--output',str(self.root/'cli')],capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(json.loads(p.stdout)['status'],'DATABASE_CONVERSION_VERIFIED')
        self.assertEqual(before,self.db.read_bytes())
        with self.assertRaises(RequestValidationError):migration.prepare_migration(self.db,self.root/'cli')

    def test_backup_timeout_keeps_partial_output_unusable(self):
        self.append()
        with patch.object(migration.time,'monotonic',side_effect=[0,901]):
            with self.assertRaises(TimeoutError):self.migrate()
        report=json.loads((self.root/'converted/migration-report.json').read_text())
        self.assertEqual(report['status'],'INCOMPLETE');self.assertFalse(report['adoption_authorized'])
        self.assertEqual(self.store.event_count('P'),1)

    def test_corrupt_result_and_missing_body_cannot_produce_verified_candidate(self):
        self.append()
        with closing(sqlite3.connect(self.db)) as c:
            raw=json.loads(c.execute('SELECT events_json FROM control_idempotency').fetchone()[0])
            raw[0]['payload']['extra']['integer']=2
            c.execute('UPDATE control_idempotency SET events_json=?',(json.dumps(raw),));c.commit()
        with self.assertRaises(RequestValidationError):self.migrate()
        self.assertEqual(json.loads((self.root/'converted/migration-report.json').read_text())['status'],'INCOMPLETE')
        compact=self.root/'broken.sqlite3';s=Store(compact,physical_format=COMPACT)
        s.append_batch('P',[{'event_type':'BUILD_SOURCES_CAPTURED','payload':{'snapshot':{'sources':[{'text':'body'}]}}}],
            expected_revision=0,idempotency_key='one',created_at='time')
        with closing(sqlite3.connect(compact)) as c:
            c.execute('DROP TRIGGER control_source_bodies_reject_delete');c.execute('DELETE FROM control_source_bodies')
            from harness_foundry_factory.revision_bodies import BODY_TRIGGERS
            c.execute(BODY_TRIGGERS['control_source_bodies_reject_delete']);c.commit()
        with self.assertRaises(RequestValidationError):migration.prepare_migration(compact,self.root/'broken-copy',target_format=INLINE)

    def test_empty_store_and_large_changed_body_are_not_lost(self):
        empty=self.migrate();self.assertEqual(empty['logical_comparison']['events'],0)
        self.append('x'*512*1024);self.append('x'*512*1024+'y',key='changed')
        report=migration.prepare_migration(self.db,self.root/'large')
        self.assertEqual(report['logical_comparison']['events'],2)
        with Store(report['candidate']['path'],read_only=True)._connection() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM control_source_bodies').fetchone()[0],2)

    def test_missing_link_target_is_recorded_as_gap_not_available_evidence(self):
        directory=self.root/'observations';directory.mkdir();(directory/'missing').symlink_to('not-present')
        result=migration.evidence_inventory([{'path':str(directory),'kind':'tree','role':'ATTACHMENTS'}])
        self.assertEqual(result[0]['status'],'UNAVAILABLE')
        self.assertEqual(result[0]['files']['missing']['link'],'not-present')

    def test_bound_file_symlink_keeps_content_identity_and_detects_real_changes(self):
        original=self.root/'real output';original.write_bytes(b'accepted')
        alias=self.root/'allowed alias';alias.symlink_to(original.name)
        declaration=[{'path':str(alias),'kind':'file','role':'ARTIFACT','expected':migration.file_fact(original)}]
        result=migration.evidence_inventory(declaration)[0]
        self.assertEqual(result['status'],'AVAILABLE');self.assertEqual(result['files']['.']['link'],original.name)
        original.write_bytes(b'changed')
        self.assertEqual(migration.evidence_inventory(declaration)[0]['status'],'BOUND_VERSION_CHANGED')
        original.unlink()
        self.assertIn(migration.evidence_inventory(declaration)[0]['status'],('UNAVAILABLE','BOUND_VERSION_CHANGED'))


    def test_unreadable_subtree_keeps_known_files_and_other_declarations(self):
        self.append();before=self.db.read_bytes()
        tree=self.root/'observations';tree.mkdir();blocked=tree/'b-denied';blocked.mkdir()
        (blocked/'hidden.json').write_text('original')
        for name in ('a.json','z.json'):(tree/name).write_text(name)
        other=self.root/'other.json';other.write_text('known')
        declarations=[{'path':str(tree),'kind':'tree','role':'REPORTS'},
                      {'path':str(other),'kind':'file','role':'OTHER_REPORT'}]
        original=os.scandir
        def scan(path):
            if Path(path)==blocked:raise PermissionError(errno.EACCES,'denied',str(path))
            return original(path)
        with patch.object(os,'scandir',side_effect=scan):report=self.migrate(evidence=declarations)
        first,second=report['external_evidence']
        self.assertEqual(first['status'],'UNAVAILABLE')
        self.assertEqual(set(first['files']),{'a.json','z.json'})
        self.assertEqual(first['errors'][0]['path'],'b-denied')
        self.assertEqual(first['errors'][0]['reason'],'PermissionError')
        self.assertEqual(second['status'],'AVAILABLE')
        self.assertEqual(report['external_evidence_status'],'REVIEW_REQUIRED')
        self.assertTrue(report['external_evidence_stable'])
        self.assertFalse(report['adoption_authorized']);self.assertEqual(report['business_commands'],0)
        self.assertEqual(before,self.db.read_bytes())
        restored=migration.evidence_inventory(declarations)
        self.assertTrue(all(r['status']=='AVAILABLE' for r in restored))
        self.assertIn('b-denied/hidden.json',restored[0]['files'])
        self.assertEqual(before,self.db.read_bytes())

    def test_unreadable_root_is_not_a_legitimate_empty_directory(self):
        blocked=self.root/'blocked';blocked.mkdir();empty=self.root/'empty';empty.mkdir()
        original=os.scandir
        def scan(path):
            if Path(path)==blocked:raise PermissionError(errno.EACCES,'denied',str(path))
            return original(path)
        with patch.object(os,'scandir',side_effect=scan):
            rows=migration.evidence_inventory([{'path':str(p),'kind':'tree','role':'REPORTS'} for p in (blocked,empty)])
        self.assertEqual(rows[0]['status'],'UNAVAILABLE')
        self.assertEqual(rows[0]['errors'][0]['path'],'.')
        self.assertEqual(rows[1]['status'],'AVAILABLE');self.assertEqual(rows[1]['files'],{})
        self.assertNotIn('errors',rows[1])

    def test_partial_directory_scan_retains_already_observed_entries(self):
        tree=self.root/'partial';tree.mkdir();known=tree/'known.json';known.write_text('known')
        class PartialScan:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def __iter__(self):
                yield type('Entry',(),{'path':str(known)})()
                raise OSError(errno.EIO,'interrupted enumeration',str(tree))
        original=os.scandir
        with patch.object(os,'scandir',side_effect=lambda p:PartialScan() if Path(p)==tree else original(p)):
            row=migration.evidence_inventory([{'path':str(tree),'kind':'tree','role':'REPORTS'}])[0]
        self.assertEqual(row['status'],'UNAVAILABLE')
        self.assertEqual(row['files']['known.json'],migration.file_fact(known))
        self.assertEqual(row['errors'][0]['errno'],errno.EIO)

    def test_file_read_failure_preserves_later_files_and_declaration(self):
        tree=self.root/'reports';tree.mkdir()
        for name in ('a.json','b.json','z.json'):(tree/name).write_text(name)
        declaration={'path':str(tree),'kind':'tree','role':'REPORTS'};original=migration.file_fact
        def read(path):
            if path==tree/'b.json':raise OSError(errno.EIO,'unreadable',str(path))
            return original(path)
        with patch.object(migration,'file_fact',side_effect=read):row=migration.evidence_inventory([declaration])[0]
        self.assertEqual(row['status'],'UNAVAILABLE');self.assertEqual(row['declaration'],declaration)
        self.assertEqual(set(row['files']),{'a.json','z.json'})
        self.assertEqual(row['errors'][0]['path'],'b.json')

    def test_entry_metadata_failure_is_not_silently_omitted(self):
        tree=self.root/'reports';tree.mkdir();blocked=tree/'metadata.json';blocked.write_text('original')
        (tree/'known.json').write_text('known');original=Path.stat
        def stat(path,*args,**kwargs):
            if path==blocked:raise PermissionError(errno.EACCES,'denied',str(path))
            return original(path,*args,**kwargs)
        with patch.object(Path,'stat',stat):row=migration.evidence_inventory([{'path':str(tree),'kind':'tree','role':'REPORTS'}])[0]
        self.assertEqual(row['status'],'UNAVAILABLE');self.assertIn('known.json',row['files'])
        self.assertEqual(row['errors'][0]['path'],'metadata.json')

    def test_empty_directories_and_links_keep_their_existing_scope(self):
        tree=self.root/'reports';tree.mkdir();(tree/'empty').mkdir()
        target=self.root/'external';target.mkdir();(target/'not-selected').write_text('outside tree')
        (tree/'directory-link').symlink_to(target,target_is_directory=True)
        (tree/'original').write_text('known');(tree/'file-link').symlink_to('original')
        calls=[];original=os.scandir
        def scan(path):calls.append(Path(path));return original(path)
        with patch.object(os,'scandir',side_effect=scan):
            rows=migration.evidence_inventory([{'path':str(p),'kind':'tree','role':'REPORTS'} for p in (tree,tree/'empty')])
        self.assertEqual([r['status'] for r in rows],['AVAILABLE','AVAILABLE'])
        self.assertFalse(rows[0]['files']['directory-link']['target_contents_checked'])
        self.assertTrue(rows[0]['files']['file-link']['target_is_file'])
        self.assertEqual(rows[0]['files']['file-link']['sha256'],rows[0]['files']['original']['sha256'])
        self.assertEqual(rows[1]['files'],{})
        self.assertNotIn(target,calls);self.assertNotIn(tree/'directory-link',calls)
        self.assertNotIn('directory-link/not-selected',rows[0]['files'])


class RecoveryMigrationTests(unittest.TestCase):
    def migrated(self,f,name='conversion'):
        before=read_build(f.store.database_path,f.program)
        output=f.root/name
        report=migration.prepare_migration(f.store.database_path,output,evidence=[
            {'path':str(f.verifier),'kind':'tree','role':'CHECKER'},
            {'path':str(f.workspace),'kind':'tree','role':'DISPOSABLE_ACCEPTED_PRODUCTS'}])
        old=f.store;f.store=Store(output/'candidate.sqlite3')
        after=read_build(f.store.database_path,f.program)
        before.pop('physical_format');after.pop('physical_format')
        # Controller path is transport metadata; event-bound absolute paths remain unchanged.
        self.assertEqual(canonical_json(before),canonical_json(after))
        self.assertEqual(report['logical_comparison']['events'],old.event_count(f.program))
        return old,report

    def test_accepted_reuse_and_multi_prepared_counts_survive(self):
        h=rebind.RebindTests();h.setUp();self.addCleanup(h.doCleanups);f=h.f
        f.prepare();f.controller().advance(f.prepared_id,advance_mode='ONE_ATTEMPT');new=h.rebind()
        old,report=self.migrated(f);calls=len(f.runner.invocations)
        for _ in range(2):read_build(f.store.database_path,f.program)
        self.assertEqual(len(f.runner.invocations),calls);self.assertEqual(h.budget(new)['attempts_consumed'],1)
        self.assertEqual(f.controller().advance(new)['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(h.budget(new)['attempts_consumed'],2)
        self.assertEqual(len(f.runner.invocations)-calls,2)  # Remaining producer + its checker only.

    def test_only_reverify_recovery_reuses_full_capture_and_retains_failed_history(self):
        h=correction.CheckerCorrectionTests();h.setUp();self.addCleanup(h.doCleanups);f=h.f
        h.prepare_failure(whole_budget=True);new,evidence=h.new_binding(complete=h.attempt_id);h.derive(new,evidence)
        def stop(invocation,result):h.runner.after_run=None;raise support.InjectedControllerCrash()
        h.runner.after_run=stop
        with self.assertRaises(support.InjectedControllerCrash):f.controller().advance(new,advance_mode='ONE_ATTEMPT')
        before_calls=len(h.runner.invocations);old,report=self.migrated(f)
        self.assertTrue(report['recorded_recovery_paths'])
        self.assertEqual(f.controller().advance(new,advance_mode='ONE_ATTEMPT')['attempt_status'],'ACCEPTED')
        self.assertEqual([i['case_id'] for i in h.runner.invocations[before_calls:]],['REJECT-MALFORMED'])
        calls=len(h.runner.invocations)
        for _ in range(2):read_build(f.store.database_path,f.program)
        self.assertEqual(len(h.runner.invocations),calls)
        history=project_budget_attempts(f.events(),new)
        self.assertEqual(history[h.attempt_id]['status'],'BLOCKED')
        budget=attempt_budget(f.scope,list(history.values()))
        self.assertEqual(budget['attempts_consumed'],1);self.assertEqual(budget['checker_reverification_rounds'],1)
        self.assertEqual(old.event_count(f.program),report['logical_comparison']['events'])

    def test_revocation_and_unknown_effect_are_not_erased(self):
        f=support.BuildRuntimeTests();f.setUp();self.addCleanup(f.doCleanups);f.prepare()
        def interrupted(invocation,before):before();raise support.InjectedControllerCrash()
        f.runner=interrupted
        with self.assertRaises(support.InjectedControllerCrash):f.advance()
        revoke_build_authorization(f.store,f.program,f.prepared_id,**f.kwargs('revoke'))
        self.migrated(f)
        with patch.object(f,'runner',side_effect=AssertionError('must not replay')):
            result=f.advance()
        self.assertEqual(result['status'],'BUILD_STOPPED')
        self.assertEqual(read_build(f.store.database_path,f.program)['authorizations'][-1]['budget']['attempts_consumed'],1)

    def test_resource_capture_checker_attachment_restore_and_cleanup_use_original_paths(self):
        h=resources.BuildResourceIntegrationTests();self.addCleanup(h.doCleanups);f=h.fixture();f.prepare()
        capture=[];controller=f.controller();append=controller._append
        def stop(kind,payload,revision,key):
            if kind=='BUILD_COMMAND_OBSERVED' and payload['phase']=='VERIFICATION' and not capture:
                capture.append(payload);raise support.InjectedControllerCrash()
            return append(kind,payload,revision,key)
        with patch.object(controller,'_append',side_effect=stop):
            with self.assertRaises(support.InjectedControllerCrash):controller.advance(f.prepared_id)
        invocation=capture[0]
        observation=Path(invocation['observation_root']);attachment=observation/'reports/summary.json'
        original=attachment.read_bytes();expected=migration.file_fact(attachment)
        prepared=next(e['payload'] for e in f.events() if e['event_id']==f.prepared_id)
        checker=Path(prepared['verifier_source']['runtime_root'])
        evidence=[{'path':str(attachment),'kind':'file','role':'RESOURCE_REPORT','expected':expected},
                  {'path':str(observation),'kind':'tree','role':'CAPTURE_AND_CLEANUP'},
                  {'path':str(checker),'kind':'tree','role':'PROTECTED_CHECKER'}]
        attachment.unlink()  # Only this disposable fixture; preserve exact original bytes.
        report=migration.prepare_migration(f.store.database_path,f.root/'resource-migration',evidence=evidence)
        self.assertEqual(report['external_evidence_status'],'REVIEW_REQUIRED')
        self.assertEqual(report['external_evidence'][0]['status'],'UNAVAILABLE')
        f.store=Store(report['candidate']['path']);before=f.store.event_count(f.program)
        attachment.write_bytes(original)
        self.assertTrue(all(r['status']=='AVAILABLE' for r in migration.evidence_inventory(evidence)))
        self.assertEqual(f.store.event_count(f.program),before)
        self.assertEqual(f.advance()['status'],'PLAN_CHECKS_ACCEPTED')
        self.assertEqual(len(f.runner.invocations),5)
        recovered=next(e['payload'] for e in f.events('BUILD_COMMAND_OBSERVED') if e['payload']['command_id']==invocation['command_id'])
        self.assertEqual(recovered['observation_root'],str(observation))
        self.assertEqual(recovered['resource_binding']['verifier_root'],str(checker))
        self.assertEqual(recovered['result']['resource_cleanup']['status'],'CLEANED')
        calls=len(f.runner.invocations)
        for _ in range(2):read_build(f.store.database_path,f.program)
        self.assertEqual(len(f.runner.invocations),calls)
        self.assertEqual(read_build(f.store.database_path,f.program)['authorizations'][-1]['budget']['attempts_consumed'],2)


if __name__ == '__main__':unittest.main()
