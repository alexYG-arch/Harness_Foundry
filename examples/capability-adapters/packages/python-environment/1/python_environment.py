"""Bind a project Python, capture a real probe, or run one explicit project entry.

No installation, discovery command, hidden retry, network grant or scheduler.
"""

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path


_spec = importlib.util.spec_from_file_location('python_stack_runtime', Path(__file__).with_name('stack_runtime.py'))
runtime = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runtime)
PACKAGE = {'name': 'python-environment', 'version': '1'}


def absolute_directory(value):
    path = Path(value)
    if not path.is_absolute() or not path.is_dir():
        raise ValueError('supply an existing absolute directory')
    return str(path.resolve())


def bind(python, project_paths=(), module_files=(), environment=None):
    executable = Path(python)
    if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError('supply an existing absolute project Python executable')
    # Canonicalize parent aliases, retaining the final venv executable link.
    invocation = executable.parent.resolve() / executable.name
    paths = [absolute_directory(p) for p in project_paths]
    observed = [str(invocation)]
    configuration = invocation.parent.parent / 'pyvenv.cfg'
    if configuration.is_file():
        observed.append(str(configuration))
    for value in module_files:
        path = Path(value)
        if not path.is_absolute() or not path.is_file():
            raise ValueError('declared module observations require existing absolute files')
        observed.append(str(path))
    return runtime.make_profile(PACKAGE, {'project-python': str(invocation)},
        environment=environment, operations=('observe-native', 'probe', 'run'), observe_paths=observed,
        read_paths=[str(invocation.parent.parent), *paths, *observed],
        extensions={'python': {'project_paths': list(dict.fromkeys(paths)),
                               'declared_module_files': list(module_files),
                               'observation_scope': 'interpreter, optional pyvenv.cfg and explicitly declared module files; actual import observations require probe'}})


def project_paths(profile):
    values = profile.get('extensions', {}).get('python', {}).get('project_paths', [])
    if not isinstance(values, list):
        raise ValueError('python project_paths must be a list')
    return [absolute_directory(value) for value in values]


def observe_native(profile, input_path, report_dir, *, otool, adapt_loader_paths=False,
                   dependency_directories=(), timeout=900):
    """Explicit macOS metadata/linkage queries; no claim of successful imports."""
    runtime.validate_profile(profile, PACKAGE)
    if 'observe-native' not in profile['operations']:
        raise ValueError('observe-native operation is not declared by this profile')
    selected = Path(otool)
    if not selected.is_absolute() or not selected.is_file() or not os.access(selected, os.X_OK):
        raise ValueError('select an existing absolute otool executable')
    report = Path(report_dir).resolve()
    report.mkdir(parents=True, exist_ok=False)
    result = {'status': 'ERROR', 'native_import_verified': False, 'operations': [], 'issues': []}
    try:
        source = Path(input_path).resolve(strict=True)
        argv = [runtime.tool(profile, 'project-python'), '-I', '-B', str(Path(__file__).with_name('python_inspect.py')),
                '--input', str(source), '--output', str(report / 'module-locations.json')]
        for path in project_paths(profile):
            argv.extend(['--project-path', path])
        record = runtime.run_capture(argv, str(report), report / 'module-query', env=runtime.child_environment(profile),
            timeout=timeout, metadata={'package': PACKAGE, 'operation': 'observe-module-locations',
                                       'input_sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
        result['operations'].append({'operation': 'observe-module-locations', 'record': record})
        if record['status'] != 'FINISHED' or record.get('returncode') != 0:
            raise ValueError('selected interpreter could not observe module locations; inspect module-query capture')
        facts = json.loads((report / 'module-locations.json').read_text(encoding='utf-8'))
        if facts.get('status') != 'OBSERVED' or facts['python']['system'] != 'Darwin':
            raise ValueError('otool native observation currently requires an observed macOS interpreter')
        spec = importlib.util.spec_from_file_location('python_native_dependencies', Path(__file__).with_name('native_dependencies.py'))
        dependencies = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dependencies)
        linked = dependencies.discover_dependencies(facts['native_files'], tool=str(selected),
            report_dir=report / 'dependencies', environment=runtime.child_environment(profile),
            dependency_directories=dependency_directories, timeout=timeout, metadata={'package': PACKAGE}, runtime=runtime)
        result['operations'].extend(linked['operations'])
        result['aliases'] = linked['aliases']
        result['read_path_proposals'] = linked['read_path_proposals']
        if linked['status'] != 'OBSERVED' or linked.get('complete') is not True:
            result['issues'].extend(linked.get('issues', []))
            raise ValueError('native dependency observation is incomplete; retain diagnostics without installing or guessing')
        environment = deepcopy(profile['environment'])
        if adapt_loader_paths:
            for key, values in (('DYLD_LIBRARY_PATH', linked['library_dirs']), ('DYLD_FRAMEWORK_PATH', linked['framework_dirs'])):
                if key in environment.get('set', {}):
                    raise ValueError('explicit environment.set conflicts with loader adaptation: ' + key)
                if values:
                    environment.setdefault('prepend', {})[key] = list(dict.fromkeys([*values, *environment.get('prepend', {}).get(key, [])]))
        tools = {**profile['tools'], 'python-otool': str(selected)}
        observed = [row['path'] for row in profile['observations']]
        observed.extend(row['path'] for row in linked['files'])
        observed.extend(row['origin'] for row in facts['modules'].values()
                        if row.get('origin') and row['origin'] not in ('built-in', 'frozen') and Path(row['origin']).is_file())
        extension = deepcopy(profile['extensions'])
        extension['path_aliases'] = linked['aliases']
        extension.setdefault('python', {}).update(
            observed_version='.'.join(map(str, facts['python']['version_info'])),
            native_observation={'complete': True, 'native_files': facts['native_files'],
                                'module_locations': facts['modules'], 'source': str(report / 'module-locations.json')})
        proposed = runtime.make_profile(PACKAGE, tools, environment=environment, operations=profile['operations'],
            observe_paths=observed, read_paths=[*profile['read_paths'], facts['python']['base_prefix'],
                *linked['library_dirs'], *linked['framework_dirs'], *linked['read_path_proposals'], *observed], extensions=extension)
        result.update(status='OBSERVED', profile=proposed, interpreter=facts['python'])
    except (OSError, ValueError, KeyError, TypeError) as error:
        result['issues'].append(str(error))
    runtime.write_new_json(report / 'native-observation.json', result)
    return result


def execute(args):
    profile = runtime.load_profile(args.profile, PACKAGE)
    for old in profile['observations']:
        if old.get('status') != 'OBSERVED' or runtime.file_observation(old['path']) != old:
            raise ValueError('declared environment file changed or is unavailable; prepare a new profile: ' + old['path'])
    if args.command not in profile['operations']:
        raise ValueError('operation is not declared by this profile')
    cwd = absolute_directory(args.cwd)
    paths = project_paths(profile)
    helper = Path(__file__).with_name('python_probe.py' if args.command == 'probe' else 'python_run.py')
    argv = [runtime.tool(profile, 'project-python'), '-I', '-B', str(helper)]
    metadata = {'package': PACKAGE, 'operation': args.command, 'profile_sha256': runtime.profile_digest(profile)}
    if args.command == 'probe':
        specification = Path(args.input).resolve(strict=True)
        argv.extend(['--input', str(specification), '--output', str(Path(args.report_dir).resolve() / 'observation.json')])
        metadata['input_sha256'] = hashlib.sha256(specification.read_bytes()).hexdigest()
    elif args.script:
        script = Path(args.script).resolve(strict=True)
        argv.extend(['--script', str(script)])
        metadata['script_sha256'] = hashlib.sha256(script.read_bytes()).hexdigest()
    else:
        argv.extend(['--module-name', args.module_name])
    for path in paths:
        argv.extend(['--project-path', path])
    if args.command == 'run':
        argv.extend(['--', *(args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments)])
    return runtime.run_capture(argv, cwd, args.report_dir, env=runtime.child_environment(profile),
                               timeout=args.timeout, metadata=metadata)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest='command', required=True)
    preparation = commands.add_parser('bind', help='pure path preparation; no interpreter execution')
    preparation.add_argument('--python', required=True)
    preparation.add_argument('--project-path', action='append', default=[])
    preparation.add_argument('--observe-module-file', action='append', default=[])
    preparation.add_argument('--output', required=True)
    native = commands.add_parser('observe-native', help='record explicit macOS module/linkage queries, then propose a new profile')
    native.add_argument('--profile', required=True)
    native.add_argument('--input', required=True)
    native.add_argument('--otool', required=True)
    native.add_argument('--report-dir', required=True)
    native.add_argument('--output', required=True)
    native.add_argument('--dependency-directory', action='append', default=[])
    native.add_argument('--adapt-loader-paths', action='store_true')
    native.add_argument('--timeout', type=float, default=900)
    for name in ('probe', 'run'):
        command = commands.add_parser(name)
        command.add_argument('--profile', required=True)
        command.add_argument('--cwd', required=True)
        command.add_argument('--report-dir', required=True)
        command.add_argument('--timeout', type=float, default=900)
        if name == 'probe':
            command.add_argument('--input', required=True)
        else:
            target = command.add_mutually_exclusive_group(required=True)
            target.add_argument('--script')
            target.add_argument('--module-name')
            command.add_argument('arguments', nargs=argparse.REMAINDER)
    read = commands.add_parser('read', help='retrieve an existing capture; never rerun')
    read.add_argument('--report-dir', required=True)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'bind':
            profile = bind(args.python, args.project_path, args.observe_module_file)
            runtime.write_new_json(args.output, profile)
            result = {'status': 'PREPARED', 'profile': str(Path(args.output).resolve()), 'executed': False}
        elif args.command == 'read':
            result = runtime.read_capture(args.report_dir)
        elif args.command == 'observe-native':
            # An existing proposed profile is never a reason to rerun queries.
            if Path(args.output).exists() or Path(args.output).is_symlink():
                raise FileExistsError(args.output)
            result = observe_native(runtime.load_profile(args.profile, PACKAGE), args.input, args.report_dir,
                otool=args.otool, adapt_loader_paths=args.adapt_loader_paths,
                dependency_directories=args.dependency_directory, timeout=args.timeout)
            if result['status'] == 'OBSERVED':
                runtime.write_new_json(args.output, result['profile'])
        else:
            result = execute(args)
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps({'status': 'ERROR', 'error_type': type(error).__name__, 'error': str(error)}))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get('status') in ('PREPARED', 'OBSERVED') or result.get('status') == 'FINISHED' and result.get('returncode') == 0 else 2


if __name__ == '__main__':
    raise SystemExit(main())
