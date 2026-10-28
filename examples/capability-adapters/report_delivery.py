"""Read-only delivery evidence projection. No execution, acceptance or budget write."""
import argparse
import hashlib
import json
from pathlib import Path


def identity(manifest):
    return hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',', ':'),ensure_ascii=False).encode()).hexdigest()


def receipt_matches(record):
    ref=record.get('report_ref')
    if not isinstance(ref,dict) or not ref.get('path') or not ref.get('sha256'):return False
    try:
        raw=Path(ref['path']).read_bytes(); actual=json.loads(raw)
        if hashlib.sha256(raw).hexdigest()!=ref['sha256']:return False
        if actual.get('status') not in ('PASS','CHECKS_PASS') or actual.get('errors'):return False
        if not actual.get('checks') or any(r.get('status')!='PASS' for r in actual['checks']):return False
        if record.get('command_ref') and actual.get('command_id')!=record['command_ref']:return False
        if actual.get('attempt_id') and actual['attempt_id']!=record.get('attempt_ref'):return False
        return True
    except (OSError,ValueError,KeyError,TypeError):return False


def report(manifest, evidence, contexts=None, build_state=None):
    bound=identity(manifest);rows=[]
    for feature in manifest['features']:
        key=feature['capability']+'@'+feature['version']+':'+feature['feature']
        form=feature['final_form'];all_records=[r for r in evidence if r['feature']==key]
        context=(contexts or {}).get(key)
        applicable=[r for r in all_records if r.get('delivery_sha256')==bound and context is not None
                    and all(r.get(k)==context.get(k) and context.get(k) for k in ('input_ref','expected_ref','checker_ref','environment_ref'))]
        row={'feature':key,'form':form,'evidence':all_records,'status':'UNVERIFIED','reason':'No complete evidence for this delivery'}
        if feature['status']=='NOT_SELECTED_ON_DEMAND':row.update(status=feature['status'],reason='Not selected')
        elif form=='BUILD_ONLY':row.update(status='BUILD_ONLY',reason='Build-time use only')
        elif form=='EXCLUDED' and feature.get('decision_ids'):row.update(status='EXCLUDED',reason='Explicit decision')
        else:
            # Host supplies append-ordered observations. A later FAIL/ERROR is not erased by an older PASS.
            current=applicable[-1] if applicable else {}
            refs=all(current.get(k) for k in ('input_ref','expected_ref','checker_ref','environment_ref','report_ref'))
            runtime=current.get('behavior')=='PASS' and all(current.get(k) for k in ('command_ref','attempt_ref'))
            no_behavior=(feature['kind'] in ('material','config') and current.get('behavior')=='NOT_APPLICABLE'
                         and current.get('behavior_reason') and current.get('content_and_consumption')=='PASS')
            passed=refs and receipt_matches(current) and current.get('structure')=='PASS' and current.get('status')=='PASS'
            if form in ('AS_IS','BRIDGED') and passed and (runtime or no_behavior):
                row.update(status='DELIVERED_VERIFIED',reason='Applicable checks passed')
            elif form=='REPLACED_BY_FOUNDRY' and passed and runtime and current.get('replacement_checked') is True:
                row.update(status='REPLACED_VERIFIED',reason='Replacement checked')
            elif form=='POST_DELIVERY':
                done=passed and runtime and current.get('step_ref')
                row.update(status='POST_DELIVERY_DONE' if done else 'POST_DELIVERY_PENDING',reason='Step checked' if done else 'Host step not yet verified')
            elif current:
                row['reason']='Latest applicable evidence is '+str(current.get('status','INCOMPLETE'))
        rows.append(row)
    return {'delivery_sha256':bound,'features':rows,'commands_executed':False,'budget_modified':False,
            'verified':sum(r['status'] in ('DELIVERED_VERIFIED','REPLACED_VERIFIED','POST_DELIVERY_DONE') for r in rows),
            'harness_e2e_verified':False, 'current_build_state':build_state,
            'acceptance_note':'Build state is reported independently; capability evidence does not grant acceptance.'}


def markdown(result):
    return '# Capability delivery report\n\n'+''.join('- '+r['feature']+': '+r['status']+' — '+r['reason']+'\n' for r in result['features'])


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--delivery',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--contexts',type=Path,required=True);p.add_argument('--read-build',type=Path)
    a=p.parse_args();result=report(json.loads(a.delivery.read_text()),json.loads(a.evidence.read_text()),json.loads(a.contexts.read_text()),json.loads(a.read_build.read_text()) if a.read_build else None)
    with a.output.open('x') as stream:json.dump(result,stream,ensure_ascii=False,indent=2)
    print(markdown(result));return 0 if all(r.get('status') for r in result['features']) else 1

if __name__=='__main__':raise SystemExit(main())
