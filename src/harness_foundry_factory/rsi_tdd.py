"""Read-only RED/GREEN evidence association for explicitly selected behaviors.

Versions and semantic assessments are host declarations with source references,
not authenticated truth. No execution, counters, automatic repair or acceptance.
"""
from copy import deepcopy
from datetime import datetime
from .rsi_cases import require
from .rsi_review import digest
import re


MATCH_FIELDS = ('behavior_id','test_id','assertion_id','input_id','platform','environment','argv')
VERSION_FIELDS = ('implementation_version','test_version')


def stamp(value):
    require(isinstance(value,str), 'timestamp required')
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    require(parsed.tzinfo is not None, 'timezone required')
    return parsed


def _structured_result(case, ref):
    rows=[row for row in case['observations'] if row['ref']==ref]
    require(len(rows)==1, 'missing or ambiguous observation')
    row=rows[0]
    require(row['evidence_kind']=='FOUNDRY_RECORD_REPORTED', 'test result needs a structured tool report, not model prose')
    source=next(s for s in case['sources'] if s['source_id']==row['source_id'])
    require(source['parse_status']=='COMPLETE' and 'document' in source, 'test report incomplete')
    node=source['document']
    if row['locator']!='/':
        for part in row['locator'].split('/')[1:]:
            key=part.replace('~1','/').replace('~0','~')
            node=node[int(key)] if isinstance(node,list) else node[key]
    require(isinstance(node,dict), 'test observation must be an object')
    return node, source


def _successful_tests(result):
    # New collector results identify success at addSuccess, not through prose.
    if 'successes' in result:
        identities=result['successes']
        require(isinstance(identities,list) and all(isinstance(x,str) and x.strip() for x in identities),
                'invalid successful test identities')
        return set(identities)
    # Historical verbosity=2 unittest records: a header, then at most one
    # description line. Consume descriptions even when they look like headers.
    log=result.get('test_log','')
    require(isinstance(log,str),'invalid test log')
    lines=iter(log.splitlines());identities=set()
    for line in lines:
        if line.startswith(('======','------')):
            break  # Failure details and summary are not execution records.
        header=re.fullmatch(r'[^\s()]+ \(([^()\r\n]+)\)(?: \.\.\. (.*))?',line)
        if header is None:
            continue
        identity,status=header.groups()
        if status is None:
            description=next(lines,'')
            status='ok' if description.endswith(' ... ok') else None
        if status=='ok':
            identities.add(identity)
    return identities


def _run(case, run):
    require(isinstance(run,dict), 'run binding required')
    for key in ('run_id','command_id','ref',*MATCH_FIELDS,*VERSION_FIELDS):
        value=run.get(key)
        require((isinstance(value,list) and value and all(isinstance(x,str) and x for x in value))
                if key=='argv' else isinstance(value,str) and value and value!='UNKNOWN', 'missing run binding: '+key)
    stamp(run.get('started_at'));stamp(run.get('finished_at'))
    require(stamp(run['started_at']) <= stamp(run['finished_at']), 'run time reversed')
    result, source=_structured_result(case,run['ref'])
    for key in ('implementation_version','test_version','platform','environment'):
        declared=source['context'].get(key,'UNKNOWN')
        require(declared!='UNKNOWN' and declared==run[key], 'source/run version or condition mismatch: '+key)
    require(source['context'].get('phase')=='DEVELOPMENT', 'developer evidence phase not established')
    if 'command_id' in result:
        require(result['command_id']==run['command_id'], 'command binding differs from report')
    if 'argv' in result:
        require(result['argv']==run['argv'], 'command argv differs from report')
    observed_status=result.get('status')
    count=result.get('tests_run')
    valid_count=type(count) is int and count>0
    errors=result.get('errors',[])
    failures=result.get('failures',[])
    require(isinstance(errors,list) and isinstance(failures,list), 'invalid test details')
    selected=run['test_id']
    failing_tests={entry.get('test') for entry in failures+errors if isinstance(entry,dict)}
    # Unrelated suite failures/skips do not erase this test's observed outcome.
    # Unscoped incomplete records cannot establish a selected outcome safely.
    incomplete=False
    for key in ('skipped','expected_failures','unexpected_successes'):
        entries=result.get(key,[])
        require(isinstance(entries,list), 'invalid incomplete test details')
        for entry in entries:
            identity=entry.get('test') if isinstance(entry,dict) else entry
            if not isinstance(identity,str) or not identity.strip() or identity==selected:
                incomplete=True
    success=selected in _successful_tests(result)
    status='BLOCKED'
    if valid_count and observed_status in {'CHECKS_PASS','CHECKS_FAILED'} and not incomplete:
        if selected in failing_tests and not success and observed_status=='CHECKS_FAILED':
            status='FAIL'
        elif success and selected not in failing_tests and not result.get('discovery_errors'):
            status='PASS'
    return {'binding':deepcopy(run),'status':status,'reported_status':observed_status,
            'failure_kind':result.get('failure_kind'),'source_sha256':source['sha256'],
            'original_result':deepcopy(result)}


def associate_tdd(case, manifest):
    require(case.get('schema_version')=='RSI_CASE_V1', 'expected imported case')
    require(isinstance(manifest,dict) and manifest.get('case_id')==case['case_id'], 'wrong case binding')
    cycles=manifest.get('cycles');require(isinstance(cycles,list), 'cycles list required')
    refs={row['ref'] for row in case['observations']}
    rows=[];seen=set();used_pairs=set()
    def declared_assessment(value):
        return (isinstance(value,dict) and isinstance(value.get('reason'),str) and bool(value['reason'].strip())
                and isinstance(value.get('evidence_refs'),list) and bool(value['evidence_refs'])
                and all(ref in refs for ref in value['evidence_refs']))
    for cycle in cycles:
        identity=cycle.get('id') if isinstance(cycle,dict) else None
        require(isinstance(identity,str) and identity and identity not in seen,'duplicate or missing cycle id')
        seen.add(identity)
        row={'id':identity,'behavior':cycle.get('behavior'),'classification':'INSUFFICIENT_EVIDENCE',
             'evidence_pair_status':'NOT_ESTABLISHED','full_tdd_verified':False,'independent_acceptance':deepcopy(cycle.get('independent_acceptance',{'status':'NOT_RUN'})),
             'regression':deepcopy(cycle.get('regression',{'status':'NOT_RUN'})), 'limits':[]}
        if cycle.get('applicability')=='NOT_APPLICABLE':
            require(isinstance(cycle.get('reason'),str) and cycle['reason'].strip(),'not-applicable reason required')
            row.update(classification='NOT_APPLICABLE',reason=cycle['reason']);rows.append(row);continue
        require(cycle.get('applicability')=='APPLICABLE','declare applicability')
        try:
            require(cycle.get('requirement') in case['requirements'], 'public requirement mapping missing')
            row['requirement']=cycle['requirement']
            green=_run(case,cycle.get('green'));row['green']=green
            if not cycle.get('red'):
                row['classification']='GREEN_ONLY' if green['status']=='PASS' else 'UNRESOLVED'
                rows.append(row);continue
            red=_run(case,cycle['red']);row['red']=red
            pair=(red['binding']['command_id'],green['binding']['command_id'],red['binding']['test_id'])
            if pair in used_pairs:
                row.update(classification='DUPLICATE_PAIR',duplicate_of=next(r['id'] for r in rows if r.get('pair_identity')==list(pair)))
                rows.append(row);continue
            used_pairs.add(pair);row['pair_identity']=list(pair)
            if red['status']=='PASS':
                row['classification']='GREEN_ONLY';rows.append(row);continue
            if red['status']!='FAIL' or green['status']!='PASS':
                row['classification']='BLOCKED' if 'BLOCKED' in {red['status'],green['status']} else 'UNRESOLVED'
                rows.append(row);continue
            assessment=cycle.get('red_assessment',{})
            require(declared_assessment(assessment),'RED cause evidence missing')
            relation=assessment.get('relation')
            row['red_assessment']=deepcopy(assessment)
            if relation=='UNRELATED_ENVIRONMENT':
                row['classification']='BLOCKED';rows.append(row);continue
            require(relation in {'TARGET_ASSERTION','TARGET_INTERFACE_MISSING','TARGET_ENVIRONMENT_BEHAVIOR'},'RED relation unresolved')
            require(red['binding']['command_id']!=green['binding']['command_id'],'same command is not two observations')
            require(stamp(red['binding']['finished_at']) < stamp(green['binding']['started_at']),'RED/GREEN order unknown or reversed')
            differences=[key for key in MATCH_FIELDS if red['binding'][key]!=green['binding'][key]]
            if differences:
                row.update(classification='CONDITIONS_CHANGED',differences=differences);rows.append(row);continue
            if red['binding']['test_version']!=green['binding']['test_version']:
                equivalence=cycle.get('test_equivalence')
                if not (declared_assessment(equivalence) and equivalence.get('relation')=='EQUIVALENT'):
                    row.update(classification='CONDITIONS_CHANGED',differences=['test_version']);rows.append(row);continue
                row['declared_test_equivalence']=deepcopy(equivalence)
            change=cycle.get('change',{})
            require(change.get('before_version')==red['binding']['implementation_version'] and
                    change.get('after_version')==green['binding']['implementation_version'] and
                    change['before_version']!=change['after_version'] and isinstance(change.get('summary'),str) and change['summary'].strip(),
                    'implementation change binding missing')
            if cycle.get('final_version') != change['after_version']:
                final=_run(case,cycle.get('final_check'))
                require(final['status']=='PASS' and final['binding']['implementation_version']==cycle.get('final_version')
                        and all(final['binding'][k]==green['binding'][k] for k in (*MATCH_FIELDS,'test_version'))
                        and stamp(final['binding']['started_at'])>stamp(green['binding']['finished_at']),
                        'final/refactored version lacks comparable GREEN')
                row['final_check']=final
            row['change']=deepcopy(change)
            mode=cycle.get('mode')
            require(mode in {'TEST_FIRST','DEFECT_REPRODUCTION','POST_HOC_REPRODUCTION'},'development mode missing')
            if mode=='TEST_FIRST':
                require(stamp(cycle.get('test_defined_at')) <= stamp(red['binding']['started_at'])
                        and stamp(red['binding']['finished_at']) < stamp(change.get('started_at'))
                        and stamp(change['started_at']) <= stamp(green['binding']['started_at']), 'test-first ordering not established')
            elif mode=='DEFECT_REPRODUCTION':
                require(stamp(red['binding']['finished_at']) < stamp(change.get('started_at'))
                        <= stamp(green['binding']['started_at']), 'repair ordering not established')
            row.update(classification=mode,evidence_pair_status='COMPARABLE_REPORTED_RED_GREEN',
                       refactor=deepcopy(cycle.get('refactor',{'status':'NOT_RECORDED'})))
            row['limits'].append('Cause/semantic equivalence and chronology are source-backed host declarations, not independently authenticated by this report.')
        except (ValueError,KeyError,TypeError,IndexError) as error:
            row['limits'].append(str(error))
        rows.append(row)
    return {'schema_version':'RSI_TDD_REPORT_V1','case_id':case['case_id'],'case_sha256':digest(case),'association_sha256':digest(manifest),'cycles':rows,
            'independent_test_total':None,'budget_modified':False,'commands_executed':False,
            'acceptance_verified':False,'full_tdd_verified':False,
            'summary':[{'id':r['id'],'classification':r['classification'],'pair':r['evidence_pair_status'],
                        'requirement':r.get('requirement'), 'red_reason':r.get('red_assessment',{}).get('reason'),
                        'change':r.get('change',{}).get('summary'), 'limits':r['limits'],
                        'regression':r['regression'], 'independent_acceptance':r['independent_acceptance']} for r in rows]}
