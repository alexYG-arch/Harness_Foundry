"""Observe selected module locations without claiming successful native imports."""

import argparse
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import platform
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--project-path', action='append', default=[])
    args = parser.parse_args()
    for path in args.project_path:
        if not Path(path).is_absolute() or not Path(path).is_dir():
            raise ValueError('explicit existing absolute project path required')
    sys.path[0:0] = list(dict.fromkeys(args.project_path))
    specification = json.loads(Path(args.input).read_text(encoding='utf-8'))
    modules = specification.get('modules')
    if not isinstance(modules, list) or any(not isinstance(name, str) or not name for name in modules):
        raise ValueError('probe input modules must be explicit names')
    result = {'schema_version': '1', 'status': 'OBSERVED', 'native_import_verified': False,
              'python': {'executable': sys.executable, 'prefix': sys.prefix, 'base_prefix': sys.base_prefix,
                         'version': sys.version, 'version_info': list(sys.version_info[:3]),
                         'system': platform.system(), 'machine': platform.machine()},
              'modules': {}, 'native_files': [], 'issues': []}
    for name in dict.fromkeys(('_decimal', '_sqlite3', *modules)):
        try:
            # For dotted names Python may import the parent package. This is
            # an explicitly recorded query, never a pure preparation function.
            spec = importlib.util.find_spec(name)
            if spec is None:
                raise ModuleNotFoundError(name)
            native = bool(spec.origin and any(spec.origin.endswith(suffix) for suffix in importlib.machinery.EXTENSION_SUFFIXES))
            result['modules'][name] = {'origin': spec.origin, 'native_extension': native}
            if native:
                result['native_files'].append(str(Path(spec.origin).resolve(strict=True)))
        except (ImportError, ValueError, OSError) as error:
            result['issues'].append({'module': name, 'error_type': type(error).__name__, 'error': str(error)})
    if result['issues']:
        result['status'] = 'ERROR'
    with Path(args.output).open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2, ensure_ascii=False)
        output.write('\n')
    return 0 if result['status'] == 'OBSERVED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
