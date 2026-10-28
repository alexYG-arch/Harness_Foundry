"""Independent structural check against a host-protected delivery snapshot.

This does not execute functions or infer behavior PASS from structural PASS.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path

MANIFESTS=('delivery.json','capability-inventory.json','capability-inventory.md','decision-records.json')

def check(target, expected, instructions):
    target=Path(target);expected=Path(expected)
    if target.resolve()==expected.resolve() or target.resolve() in expected.resolve().parents:
        raise ValueError('protected expectations must be outside target')
    manifest=json.loads((expected/'delivery.json').read_bytes())
    if manifest['format_version']!=2:raise ValueError('expected delivery v2')
    checks=[]
    def record(name, ok, detail=''):
        checks.append({'id':name,'status':'PASS' if ok else 'FAIL','message':detail})
    for name in MANIFESTS:
        try:equal=(target/name).read_bytes()==(expected/name).read_bytes()
        except OSError:equal=False
        record('manifest:'+name,equal)
    layouts={};known=set(MANIFESTS) | set(manifest.get('support_files', {}))
    for name, expected_sha in manifest.get('support_files', {}).items():
        try: passed=hashlib.sha256((target/name).read_bytes()).hexdigest()==expected_sha
        except OSError: passed=False
        record('support:'+name,passed)
    spec=importlib.util.spec_from_file_location('delivery_check_layout',Path(__file__).with_name('delivery.py'))
    layout=importlib.util.module_from_spec(spec);spec.loader.exec_module(layout)
    for row in manifest['selections']:
        try:layout.check_layout(target/row['root'],row['layout']);passed=True
        except (OSError,ValueError,RuntimeError):passed=False
        layouts[row['name']]=passed
        for name in row['layout']:known.add(row['root'].rstrip('/')+'/'+name)
    for row in manifest.get('retained_unmanaged',[]):
        path=layout.C.relative(row['path']);known.add(path)
        try:passed=hashlib.sha256((target/path).read_bytes()).hexdigest()==row['sha256']
        except OSError:passed=False
        record('retained:'+path,passed)
        record('retained-owner:'+path,bool(row.get('owner') and row.get('decision_ref')))
    text='\n'.join(Path(p).read_text() for p in instructions)
    for f in manifest['features']:
        key='feature:'+f['capability']+'@'+f['version']+':'+f['feature']
        if f['final_form'] in ('AS_IS','BRIDGED'):
            record(key+':files',layouts.get(f['capability'],False))
            snippet=manifest['instruction_snippets'].get(f['capability'])
            record(key+':reference',bool(snippet and (target/snippet).is_file() and snippet in text
                                       and (not f.get('entry') or f['entry']['tool'] in text)))
        elif f['final_form']=='POST_DELIVERY':
            steps=f.get('post_delivery',[])
            record(key+':post-delivery',bool(steps) and all(json.dumps(s,ensure_ascii=False) in text if isinstance(s,dict) else s in text for s in steps))
        elif f['final_form']=='REPLACED_BY_FOUNDRY':
            record(key+':replacement',bool(f.get('replacement')) and str(f['replacement']['entry']) in text)
    ancestors={p.as_posix() for name in known for p in Path(name).parents if str(p)!='.'}
    actual={p.relative_to(target).as_posix() for p in target.rglob('*')}
    record('manifest:managed-files',actual <= known|ancestors,'Unexpected paths: '+repr(sorted(actual-known-ancestors)))
    record('forbidden:host-private',all(not any(part in ('materials.json','factory.sqlite3','__pycache__') for part in Path(name).parts) for name in actual))
    passed=all(c['status']=='PASS' for c in checks)
    return {'schema_version':'1.0','case_id':os.environ.get('FOUNDRY_CASE_ID','standalone'),
            'command_id':os.environ.get('FOUNDRY_COMMAND_ID','standalone'),
            'status':'CHECKS_PASS' if passed else 'CHECKS_FAILED', 'failure_kind':None if passed else 'ASSERTION',
            'checks':checks,'errors':[],'behavior_verified':False,'commands_executed':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--target',type=Path,required=True);p.add_argument('--expected',type=Path,required=True)
    p.add_argument('--instructions',type=Path,action='append',default=[]);p.add_argument('--report',type=Path,default=Path(os.environ['FOUNDRY_REPORT_DIR'])/'summary.json' if os.environ.get('FOUNDRY_REPORT_DIR') else None)
    a=p.parse_args()
    if a.report is None:p.error('--report or FOUNDRY_REPORT_DIR is required')
    try:result=check(a.target,a.expected,a.instructions)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        result={'schema_version':'1.0','case_id':os.environ.get('FOUNDRY_CASE_ID','standalone'),
                'command_id':os.environ.get('FOUNDRY_COMMAND_ID','standalone'), 'status':'CHECKS_FAILED',
                'failure_kind':'ERROR','checks':[], 'errors':[str(exc)],'behavior_verified':False,'commands_executed':False}
    a.report.parent.mkdir(parents=True, exist_ok=True)
    with a.report.open('x') as stream:json.dump(result,stream,ensure_ascii=False,indent=2)
    print(json.dumps(result,ensure_ascii=False));return 0 if result['status']=='CHECKS_PASS' else 1

if __name__=='__main__':raise SystemExit(main())
