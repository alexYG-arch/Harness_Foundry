"""Feature mapping for third-party sources; keeps original packages unchanged."""
import importlib.util
import json
from pathlib import Path
from copy import deepcopy

def module(name):
    s=importlib.util.spec_from_file_location('feature_connection_'+name,Path(__file__).with_name(name+'.py'))
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
I=module('inventory');C=module('connections')


def decision_sources(connection, package, feature_id):
    """Bind related public bytes, not installation paths or unrelated features."""
    catalog=connection['catalog'];features={f['id']:f for f in package['features']}
    tools={t['id']:t for t in package.get('tools', [])}
    skills={s['name']:s['path'] for s in catalog['skills']}
    names={catalog['descriptor'], *catalog.get('base_materials', [])};visited=set()
    snippet=package.get('delivery', {}).get('instruction_snippet')
    if snippet:names.add(snippet)
    def visit(fid):
        if fid in visited:return
        visited.add(fid);feature=features[fid]
        names.update(n for n in feature['files'] if n!='capability.json')
        names.update(skills[s] for s in feature.get('skills', []))
        refs=set(feature.get('tool_refs', []))
        if feature.get('entry', {}).get('tool'):refs.add(feature['entry']['tool'])
        if 'EXTERNAL_BINARY' in feature.get('conflict_tags', []):refs.add(package['delivery']['doctor']['tool'])
        names.update(tools[t]['path'] for t in refs)
        for dep in feature.get('requires', []):visit(dep)
    visit(feature_id)
    with C.source_files(connection['source']) as (read, _):
        files=[{'path':name,'sha256':C.digest(read(name))} for name in sorted(names)]
    return {'provider':catalog['provider'],'version':catalog['version'],'files':files}


def prepare(connection_config, loaded, config, sources):
    mappings=connection_config.get('feature_selections', [])
    native=deepcopy(connection_config.get('native', []))
    mapped_keys={s['key'] for s in mappings}
    selected_skills=[s for s in connection_config.get('skills', []) if s.partition(':')[0] not in mapped_keys]
    projections={}; bindings=[]
    by_key={r['key']:r for r in loaded['connections']}
    for selected in mappings:
        key=selected['key']
        if key in projections: raise ValueError('duplicate external feature selection')
        if key not in by_key: raise ValueError('external feature connection unavailable: '+key)
        connection=by_key[key];path=Path(selected['mapping_path']).resolve(strict=True);raw=path.read_bytes()
        mapping=json.loads(raw)
        catalog=connection['catalog']
        if mapping['provider']!=catalog['provider'] or catalog['version'] not in mapping['package_versions']:
            raise ValueError('external feature map provider/version mismatch')
        package=deepcopy(mapping['capability']);package['name']=key;package['version']=catalog['version']
        scope=I.select(package,selected,config,sources,C.digest(raw),
                       feature_source_identity=lambda fid: decision_sources(connection,package,fid))
        scope['provider']=catalog['provider'];scope['mapping_version']=mapping['version']
        scope['mapping_sha256']=C.digest(raw);scope['origin_catalog']=deepcopy(catalog)
        all_skills={s['name'] for s in catalog['skills']}
        covered={skill for f in package['features'] for skill in f.get('skills', [])}
        if not covered<=all_skills:raise ValueError('mapped Skill is absent from original catalog')
        operations=[];features={f['id']:f for f in package['features']}
        for row in scope['features']:
            f=features[row['feature']]
            row['skills']=f.get('skills', []);row['operations']=f.get('operations', [])
            if row['final_form'] in ('AS_IS','BRIDGED','BUILD_ONLY'):
                selected_skills.extend(key+':'+s for s in row['skills'])
                operations.extend(row['operations'])
                for skill in row['skills']:
                    declared=next(s['path'] for s in catalog['skills'] if s['name']==skill)
                    if declared not in row['files']:raise ValueError('selected Skill file is not a declared feature dependency')
        scope['unmapped_skills']=sorted(all_skills-covered)
        if scope['unmapped_skills']:
            scope['diagnostics'].append({'id':key,'code':'FEATURE_MAPPING_GAP','severity':'ERROR' if scope['mode']=='ALL' else 'WARNING','skills':scope['unmapped_skills']})
        matches=[n for n in native if n['key']==key]
        if matches:
            adapter_path=Path(matches[0].get('adapter_path') or module('native').adapter_for(catalog['provider'])).resolve(strict=True)
            adapter_raw=adapter_path.read_bytes();adapter=json.loads(adapter_raw)
            if mapping['adapter_sha256']!=C.digest(adapter_raw):raise ValueError('feature map adapter changed')
            covered_ops={op for f in package['features'] for op in f.get('operations', [])}
            if not covered_ops <= adapter['operations'].keys(): raise ValueError('mapped operation absent from adapter')
            unmapped=sorted(adapter['operations'].keys()-covered_ops)
            if unmapped:scope['diagnostics'].append({'id':key,'code':'FEATURE_MAPPING_GAP','severity':'ERROR' if scope['mode']=='ALL' else 'WARNING','operations':unmapped})
        if operations:
            if len(matches)!=1:raise ValueError('selected operations require one explicit native configuration')
            adapter_path=Path(matches[0].get('adapter_path') or module('native').adapter_for(catalog['provider'])).resolve(strict=True)
            adapter_raw=adapter_path.read_bytes();adapter=json.loads(adapter_raw)
            if mapping['adapter_sha256']!=C.digest(adapter_raw):raise ValueError('feature map adapter changed')
            if not set(operations)<=adapter['operations'].keys():raise ValueError('mapped operation absent from adapter')
            matches[0]['operations']=list(dict.fromkeys(operations))
            scope['adapter_sha256']=C.digest(adapter_raw)
        else:
            native=[n for n in native if n['key']!=key]
        bindings.append({'key':key,'path':str(path),'sha256':C.digest(raw)})
        projections[key]=scope
    result={**connection_config,'skills':list(dict.fromkeys(selected_skills)),'native':native}
    return result, projections, bindings
