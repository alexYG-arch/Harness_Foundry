"""Explicit optional RSI handoff files; no dispatch, acceptance or state mutation."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
from .rsi_cases import require, read_json

MODULES = ('python_startup', 'build_types', 'build_plan', 'acceptance_contract', 'source_intake', 'build_state', 'revision_store',
           'rsi_adoption', 'rsi_cases', 'rsi_review', 'rsi_tdd', 'rsi_wiki', 'test_execution')
TOOLS = ('report_rsi_adoption', 'import_rsi_case', 'rsi_review', 'report_rsi_tdd', 'rsi_wiki')
DOCS = ('RSI_ADOPTION', 'RSI_DELIVERY', 'RSI_CASE_INTAKE', 'RSI_REVIEW_AND_TDD', 'RSI_WIKI')


def relative(value):
    require(isinstance(value, str) and bool(value), 'expected relative file path')
    p = PurePosixPath(value)
    require(not p.is_absolute() and '..' not in p.parts and p.as_posix() == value
            and value != '.' and '\\' not in value, 'expected canonical relative path')
    return p


def contained(root, name):
    p = root / relative(name)
    require(p.resolve(strict=True).is_relative_to(root) and p.is_file(), 'file outside declared root')
    return p.read_bytes()


def prepare_delivery(source_root, manifest, material_root, output):
    """Stage a new selected support directory, never overwrite a Harness or old handoff."""
    source_root = Path(source_root).resolve(strict=True)
    material_root = Path(material_root).resolve(strict=True)
    require(isinstance(manifest, dict) and isinstance(manifest.get('version'), str)
            and bool(manifest['version'].strip()), 'delivery version required')
    config = manifest.get('wiki', {'collections': []})
    require(isinstance(config, dict) and isinstance(config.get('collections'), list), 'wiki collections required')
    for row in config['collections']:
        require(isinstance(row, dict), 'collection binding must be an object')
        require(relative(row.get('path')).parts[0] == 'knowledge', 'portable collections must be in knowledge/')
        require(all(isinstance(row.get(k), str) and row[k].strip() for k in ('id', 'version'))
                and row.get('visibility') in {'PUBLIC', 'PROJECT'}, 'invalid collection binding')
    require(len({r['id'] for r in config['collections']}) == len(config['collections']), 'duplicate collection')
    files = {}
    for name in MODULES:
        path = 'src/harness_foundry_factory/' + name + '.py'
        files[path] = contained(source_root, path)
    # Empty package initializer avoids unrelated development-only exports.
    files['src/harness_foundry_factory/__init__.py'] = b''
    for name in TOOLS:
        path = 'tools/' + name + '.py'
        files[path] = contained(source_root, path)
    for name in DOCS:
        path = 'docs/' + name + '.md'
        files[path] = contained(source_root, path)
    files['LICENSE'] = contained(source_root, 'LICENSE')
    materials = manifest.get('knowledge_files', [])
    require(isinstance(materials, list), 'knowledge_files must be an explicit list')
    for name in materials:
        require(relative(name).parts[0] == 'knowledge' and name not in files, 'duplicate or non-knowledge file')
        files[name] = contained(material_root, name)
    files['wiki.json'] = (json.dumps(config, ensure_ascii=False, indent=2) + '\n').encode()
    for row in config['collections']:
        name = row['path'] + '/collection.json'
        require(name in files, 'declared collection catalog not delivered: ' + name)
        catalog = read_json(files[name].decode())
        require(catalog.get('version') == row['version'], 'collection version differs')
        for entry in catalog.get('entries', []) + catalog.get('updates', []):
            name = row['path'] + '/' + str(relative(entry))
            require(name in files, 'declared knowledge entry not delivered: ' + name)
    files['AGENTS.md'] = ("# Selected RSI support\n\nRead docs/RSI_DELIVERY.md before using these optional tools. "
        "Use the task's declared interpreter and existing host authorization. "
        "Wiki is advice, Reviewer is an opinion, and development GREEN is not independent acceptance. "
        "No match or inapplicable TDD does not block ordinary work.\n").encode()
    receipt = {'schema_version': 'RSI_DELIVERY_V1', 'version': manifest['version'],
               'files': {p: hashlib.sha256(raw).hexdigest() for p, raw in sorted(files.items())},
               'python_requires': '>=3.11', 'third_party_python_dependencies': [],
               'host_tools': ['declared Python interpreter', 'existing Foundry generic Build host for selected Reviewer'],
               'runtime_authorized': False, 'product_accepted': False, 'budget_modified': False}
    files['DELIVERY_MANIFEST.json'] = (json.dumps(receipt, ensure_ascii=False, indent=2) + '\n').encode()
    output = Path(output)
    # This is a material preparation operation, not a Program or generated product acceptance.
    output.mkdir(parents=False, exist_ok=False)
    try:
        for name, raw in files.items():
            p = output / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(raw)
    except BaseException:
        shutil.rmtree(output)
        raise
    return receipt
