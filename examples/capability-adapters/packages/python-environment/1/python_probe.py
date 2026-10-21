"""One real import/native-extension observation in the selected interpreter.

This public fixture contains no private expectation or business acceptance.
"""

import argparse
import hashlib
import importlib
import importlib.machinery
import json
import os
from pathlib import Path
import platform
import re
import sys


BASE_MODULES = ('decimal', '_decimal', 'sqlite3', '_sqlite3')


def read_input(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict) or value.get('schema_version') != '1':
        raise ValueError('probe input requires schema_version 1')
    modules = value.get('modules')
    if (not isinstance(modules, list) or len(modules) != len(set(modules))
            or any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z_]\w*(\.[A-Za-z_]\w*)*', v) for v in modules)):
        raise ValueError('modules must be a unique list of dotted Python names')
    values, integers = value.get('decimal_values'), value.get('sqlite_values')
    if not isinstance(values, list) or not values or any(not isinstance(v, str) for v in values):
        raise ValueError('decimal_values requires nonempty decimal strings')
    if not isinstance(integers, list) or not integers or any(type(v) is not int for v in integers):
        raise ValueError('sqlite_values requires nonempty integer values')
    return value


def file_fact(path):
    path = Path(path)
    raw = path.read_bytes()
    return {'path': str(path), 'resolved_path': str(path.resolve(strict=True)), 'status': 'OBSERVED',
            'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def observe_module(name):
    module = importlib.import_module(name)
    spec = getattr(module, '__spec__', None)
    origin = getattr(spec, 'origin', None)
    result = {'name': name, 'imported': True, 'origin': origin,
              'version': str(module.__version__) if hasattr(module, '__version__') else None}
    if origin and origin not in ('built-in', 'frozen'):
        result['file'] = file_fact(origin)
    else:
        result['file'] = None
    locations = getattr(spec, 'submodule_search_locations', None)
    result['search_locations'] = [str(Path(p).resolve()) for p in locations] if locations is not None else []
    result['native_extension'] = bool(origin and any(origin.endswith(s) for s in importlib.machinery.EXTENSION_SUFFIXES))
    return result


def observe(input_path, project_paths):
    # Explicit paths replace only the isolated mode's omitted project roots.
    # They do not remove the selected venv's own site-packages.
    paths = []
    for value in project_paths:
        path = Path(value)
        if not path.is_absolute() or not path.is_dir():
            raise ValueError('project paths must be existing absolute directories')
        paths.append(str(path.resolve()))
    sys.path[0:0] = list(dict.fromkeys(paths))
    specification = read_input(input_path)
    result = {'schema_version': '1', 'status': 'OBSERVING',
              'input_sha256': hashlib.sha256(Path(input_path).read_bytes()).hexdigest(),
              'python': {'executable': sys.executable, 'resolved_executable': str(Path(sys.executable).resolve()),
                         'prefix': sys.prefix, 'base_prefix': sys.base_prefix, 'version': sys.version,
                         'version_info': list(sys.version_info[:3]), 'isolated': bool(sys.flags.isolated),
                         'no_site': bool(sys.flags.no_site), 'system': platform.system(), 'machine': platform.machine()},
              'project_paths': paths, 'modules': {}, 'errors': []}
    for name in dict.fromkeys((*BASE_MODULES, *specification['modules'])):
        try:
            result['modules'][name] = observe_module(name)
        except Exception as error:
            result['modules'][name] = {'name': name, 'imported': False, 'error_type': type(error).__name__, 'error': str(error)}
            result['errors'].append({'stage': 'import', 'module': name, 'error_type': type(error).__name__, 'error': str(error)})
    if not result['errors']:
        try:
            from decimal import Decimal, localcontext
            import sqlite3
            with localcontext() as context:
                context.prec = 50
                values = [Decimal(v) for v in specification['decimal_values']]
                if any(not v.is_finite() for v in values):
                    raise ValueError('probe decimal values must be finite')
                total = sum(values, Decimal(0))
            with sqlite3.connect(':memory:') as connection:
                connection.execute('CREATE TABLE sample (value INTEGER NOT NULL)')
                connection.executemany('INSERT INTO sample VALUES (?)', ((v,) for v in specification['sqlite_values']))
                count, integer_sum = connection.execute('SELECT COUNT(*), SUM(value) FROM sample').fetchone()
            result['calculation'] = {'decimal_sum': str(total), 'sqlite_count': count, 'sqlite_sum': integer_sum}
        except Exception as error:
            result['errors'].append({'stage': 'native-calculation', 'error_type': type(error).__name__, 'error': str(error)})
    result['status'] = 'ERROR' if result['errors'] else 'OBSERVED'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--project-path', action='append', default=[])
    args = parser.parse_args()
    output = Path(args.output)
    # Reserve the output before any imports with project-owned side effects.
    with output.open('x', encoding='utf-8') as stream:
        try:
            result = observe(args.input, args.project_path)
        except (OSError, ValueError, TypeError) as error:
            result = {'schema_version': '1', 'status': 'ERROR', 'errors': [
                {'stage': 'input', 'error_type': type(error).__name__, 'error': str(error)}]}
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    return 0 if result['status'] == 'OBSERVED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
