"""Explicit Qt/CMake environment discovery, observation and small real probes.

No installer, permissions policy, retries, model calls or budget authority. Every
process is recorded under a fresh caller-selected report directory.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import sys
import xml.etree.ElementTree as ET


def _sibling(name):
    path = Path(__file__).resolve().with_name(name + '.py')
    spec = importlib.util.spec_from_file_location('_qt_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime = _sibling('stack_runtime')
native_dependencies = _sibling('native_dependencies')
PACKAGE = {'name': 'qt-cmake', 'version': '2'}
OPERATIONS = ['configure', 'build', 'test', 'run', 'observe', 'probe']


def _absolute(value, kind='file'):
    path = Path(value)
    if not path.is_absolute():
        raise ValueError('explicit absolute path required: ' + str(value))
    if kind == 'directory' and not path.is_dir() or kind == 'file' and not path.is_file():
        raise ValueError('selected ' + kind + ' unavailable: ' + str(value))
    return path


def sdk_config(sdk):
    root = _absolute(sdk, 'directory').resolve(strict=True)
    config = root / 'lib/cmake/Qt6/Qt6Config.cmake'
    if not config.is_file():
        raise ValueError('selected Qt SDK has no lib/cmake/Qt6/Qt6Config.cmake')
    return root, config


def core_library(sdk):
    root = Path(sdk)
    candidates = [root / 'lib/QtCore.framework/Versions/A/QtCore',
                  root / 'lib/QtCore.framework/QtCore', root / 'lib/libQt6Core.dylib',
                  root / 'lib/libQt6Core.so', root / 'bin/Qt6Core.dll']
    found = {str(p.resolve(strict=True)) for p in candidates if p.is_file()}
    if len(found) != 1:
        raise ValueError('QtCore library missing or ambiguous in selected SDK')
    return Path(next(iter(found)))


def discover(tools, sdk_candidates, *, environment=None, read_paths=()):
    """Pure selected-path discovery; no subprocess or broad package-manager scan."""
    candidates = []
    diagnostics = []
    for value in sdk_candidates:
        try:
            sdk, config = sdk_config(value)
            if str(sdk) not in [str(row[0]) for row in candidates]:
                candidates.append((sdk, config))
        except (OSError, ValueError) as error:
            diagnostics.append({'path': str(value), 'issue': str(error)})
    if len(candidates) != 1:
        return {'status': 'INCOMPLETE', 'profile': None, 'diagnostics': diagnostics +
                [{'issue': 'select one available Qt SDK', 'candidates': [str(row[0]) for row in candidates]}]}
    sdk, config = candidates[0]
    selected = dict(tools)
    for role in ('qt-python', 'cmake', 'ctest'):
        path = _absolute(selected.get(role, ''))
        if not os.access(path, os.X_OK):
            raise ValueError('selected tool is not executable: ' + role)
    if 'qmake' not in selected:
        qmake = [sdk / 'bin/qmake', sdk / 'bin/qmake6']
        qmake = [p for p in qmake if p.is_file() and os.access(p, os.X_OK)]
        if qmake:
            selected['qmake'] = str(qmake[0])
    core = core_library(sdk)
    observed = [config, core]
    # These actual selected CMake metadata files affect Qt target discovery.
    for relative in ('lib/cmake/Qt6Core/Qt6CoreConfig.cmake',
                     'lib/cmake/Qt6Core/Qt6CoreTargets.cmake',
                     'lib/cmake/Qt6CoreTools/Qt6CoreToolsTargets.cmake'):
        item = sdk / relative
        if item.is_file():
            observed.append(item)
    profile = runtime.make_profile(PACKAGE, selected,
        environment=environment or {'set': {}, 'prepend': {}}, operations=OPERATIONS,
        observe_paths=[str(p) for p in observed], read_paths=[str(sdk), *map(str, read_paths)],
        extensions={'qt': {'sdk': str(sdk), 'sdk_requested': list(map(str, sdk_candidates)),
            'cmake_dir': str(config.parent), 'core_library': str(core),
            'dependency_observation': 'NOT_OBSERVED', 'loader_adaptation': False}})
    return {'status': 'READY', 'profile': profile, 'diagnostics': diagnostics,
            'probes_executed': False}


def load_profile(path):
    profile = runtime.load_profile(path, expected_package=PACKAGE)
    qt = profile.get('extensions', {}).get('qt', {})
    sdk, config = sdk_config(qt.get('sdk', ''))
    if str(config.parent) != qt.get('cmake_dir'):
        raise ValueError('Qt CMake directory does not match selected SDK')
    if str(core_library(sdk)) != qt.get('core_library'):
        raise ValueError('selected QtCore library changed; observe and rebind the environment')
    return profile


def environment(profile, inherited=None):
    return runtime.child_environment(profile, inherited=inherited)


def _query(profile, role, arguments, report, operation):
    return runtime.run_capture([runtime.tool(profile, role), *arguments],
        cwd=str(Path(report).parent), report_dir=str(report),
        env=environment(profile), metadata={'operation': operation, 'package': PACKAGE})


def _output(directory, record):
    if record.get('status') != 'FINISHED' or record.get('returncode') != 0:
        raise ValueError('environment query failed; inspect ' + str(directory))
    return (Path(directory) / 'stdout.txt').read_text(encoding='utf-8', errors='replace')


_dependency_path = native_dependencies.dependency_path


def observe(profile, report_dir, *, adapt_loader_paths=False, dependency_directories=()):
    """Explicit queries, with optional known macOS loader-path adaptation.

This process observes selected files, not their sandbox accessibility. Native
probe evidence must come from each actual receiver's declared permission scope.
"""
    report = Path(report_dir).resolve()
    report.mkdir(parents=True, exist_ok=False)
    records, issues, versions, files = [], [], {}, []
    qt = dict(profile['extensions']['qt'])
    library_dirs, framework_dirs, aliases, read_path_proposals = [], [], [], []
    try:
        for role in ('cmake', 'ctest'):
            directory = report / role
            record = _query(profile, role, ['--version'], directory, 'observe-' + role)
            records.append({'operation': role, 'path': str(directory), 'record': record})
            versions[role] = _output(directory, record).splitlines()[0]
        if 'otool' in profile['tools']:
            dependency_result = native_dependencies.discover_dependencies(
                [qt['core_library']], tool=runtime.tool(profile, 'otool'),
                report_dir=report / 'dependencies', environment=environment(profile),
                dependency_directories=dependency_directories,
                metadata={'package': PACKAGE}, runtime=runtime)
            records.extend(dependency_result['operations'])
            files.extend(dependency_result['files'])
            aliases = dependency_result['aliases']
            read_path_proposals = dependency_result['read_path_proposals']
            library_dirs = dependency_result['library_dirs']
            framework_dirs = dependency_result['framework_dirs']
            if dependency_result['status'] != 'OBSERVED':
                raise ValueError('; '.join(dependency_result['issues']))
            qt['dependency_observation'] = 'OBSERVED_SELECTED_CLOSURE'
        elif adapt_loader_paths:
            raise ValueError('loader adaptation requires an explicitly bound otool')
        else:
            qt['dependency_observation'] = 'NOT_OBSERVED'
        updated = json.loads(json.dumps(profile))
        if adapt_loader_paths:
            if platform.system() != 'Darwin':
                raise ValueError('DYLD adaptation is scoped to the observed macOS Qt layout')
            prepend = updated['environment']['prepend']
            for key, values in (('DYLD_FRAMEWORK_PATH', framework_dirs), ('DYLD_LIBRARY_PATH', library_dirs)):
                old = prepend.get(key, [])
                if key in updated['environment']['set']:
                    raise ValueError('explicit environment set conflicts with loader adaptation: ' + key)
                prepend[key] = list(dict.fromkeys([*old, *values]))
            qt['loader_adaptation'] = True
        qt['observed_versions'] = versions
        updated['extensions']['qt'] = qt
        if 'otool' in profile['tools']:
            updated['extensions']['path_aliases'] = aliases
        known = {json.dumps(row, sort_keys=True) for row in updated['observations']}
        for row in files:
            if json.dumps(row, sort_keys=True) not in known:
                updated['observations'].append(row)
        updated['read_paths'] = list(dict.fromkeys([*updated['read_paths'],
            *library_dirs, *framework_dirs, *read_path_proposals]))
        if 'qmake' in updated['tools']:
            directory = report / 'qmake'
            record = _query(updated, 'qmake', ['-query'], directory, 'observe-qmake')
            records.append({'operation': 'qmake', 'path': str(directory), 'record': record})
            query = _output(directory, record)
            values = dict(line.split(':', 1) for line in query.splitlines() if ':' in line)
            prefix = values.get('QT_INSTALL_PREFIX')
            qt['qmake_prefix_matches_selected_sdk'] = bool(prefix and str(Path(prefix).resolve()) == qt['sdk'])
            # Distribution qmake prefixes may intentionally name a shared prefix.
            # Keep this observation; configure uses the selected Qt CMake metadata,
            # and only the real probe establishes whether that combination works.
            qt['qmake_query'] = values
        result = {'status': 'OBSERVED', 'complete': True, 'profile': updated,
                  'operations': records, 'issues': [], 'native_probe': False}
    except (OSError, ValueError, IndexError) as error:
        issues.append(str(error))
        result = {'status': 'ERROR', 'complete': False, 'profile': None,
                  'operations': records, 'issues': issues, 'native_probe': False}
    result.update(aliases=aliases, read_path_proposals=read_path_proposals)
    runtime.write_new_json(report / 'observation.json', result)
    return result


def configure_definitions(profile, definitions):
    """Pin selected Qt metadata; caller can add project definitions explicitly."""
    qt = profile['extensions']['qt']
    pairs = {}
    for value in definitions:
        if '=' not in value or not value.split('=', 1)[0]:
            raise ValueError('--define requires NAME[:TYPE]=VALUE')
        key, content = value.split('=', 1)
        base = key.split(':', 1)[0]
        if base in pairs and pairs[base][1] != content:
            raise ValueError('conflicting CMake definitions: ' + base)
        pairs[base] = (key, content)
    required = {'Qt6_DIR': qt['cmake_dir']}
    for component in ('Core', 'CoreTools'):
        directory = Path(qt['sdk']) / ('lib/cmake/Qt6' + component)
        if directory.is_dir():
            required['Qt6' + component + '_DIR'] = str(directory)
    if 'compiler' in profile['tools']:
        required['CMAKE_CXX_COMPILER'] = runtime.tool(profile, 'compiler')
    for key, value in required.items():
        if key in pairs and Path(pairs[key][1]).resolve() != Path(value).resolve():
            raise ValueError('project Qt selection conflicts with bound profile: ' + key)
        pairs[key] = (key + ':PATH', value)
    return [key + '=' + value for key, value in pairs.values()]


def probe(profile, work_dir, report_dir, *, receiver):
    """Declared configure/build/CTest/CLI flow for a public QtCore smoke fixture."""
    work = Path(work_dir).resolve()
    report = Path(report_dir).resolve()
    if work.exists() or report.exists():
        raise FileExistsError('probe work and report directories must be fresh; read old evidence instead')
    work.mkdir(parents=True)
    report.mkdir(parents=True)
    source = work / 'source'
    source.mkdir()
    (source / 'CMakeLists.txt').write_bytes(Path(__file__).with_name('probe-CMakeLists.txt').read_bytes())
    (source / 'main.cpp').write_bytes(Path(__file__).with_name('probe-main.cpp').read_bytes())
    build = work / 'build'
    build.mkdir()
    cmake, ctest = runtime.tool(profile, 'cmake'), runtime.tool(profile, 'ctest')
    executable = build / ('qt_environment_probe.exe' if os.name == 'nt' else 'qt_environment_probe')
    operations = [
        ('configure', [cmake, '-S', str(source), '-B', str(build),
            *['-D' + value for value in configure_definitions(profile, [])]]),
        ('build', [cmake, '--build', str(build)]),
        ('test', [ctest, '--test-dir', str(build), '--output-on-failure', '--no-tests=error',
                  '--output-junit', str(report / 'test/junit.xml')]),
        ('run', [str(executable)])]
    records = []
    result = {'status': 'ERROR', 'complete': False, 'profile_sha256': runtime.profile_digest(profile),
              'receiver': receiver, 'operation': 'probe', 'operations': records, 'issues': [],
              'observations_complete': profile['extensions']['qt']['dependency_observation'] == 'OBSERVED_SELECTED_CLOSURE'}
    for operation, argv in operations:
        directory = report / operation
        record = runtime.run_capture(argv, cwd=str(build), report_dir=str(directory),
            env=environment(profile), metadata={'operation': operation, 'package': PACKAGE})
        records.append({'operation': operation, 'path': str(directory), 'record': record})
        if record.get('status') != 'FINISHED' or record.get('returncode') != 0:
            result['issues'].append('probe ' + operation + ' failed; inspect retained raw command evidence')
            break
    else:
        try:
            _check_probe_output(report)
            result.update(status='PASS', complete=True)
        except (OSError, ValueError, ET.ParseError) as error:
            result['issues'].append(str(error))
    runtime.write_new_json(report / 'probe.json', result)
    return result


def _check_probe_output(report):
    output = (report / 'run/stdout.txt').read_text(encoding='utf-8').strip()
    if output != 'QtCore:3':
        raise ValueError('unexpected actual QtCore output: ' + output)
    root = ET.parse(report / 'test/junit.xml').getroot()
    cases = list(root.iter('testcase'))
    if (root.tag not in ('testsuite', 'testsuites') or len(cases) != 1
            or cases[0].get('name') != 'qt-environment-probe'
            or any(cases[0].find(name) is not None for name in ('failure', 'error', 'skipped'))
            or cases[0].get('status', '').lower() in ('fail', 'failed', 'notrun', 'disabled', 'skipped')
            or any(int(suite.get(field, '0')) > 0 for suite in root.iter('testsuite')
                   for field in ('failures', 'errors', 'skipped', 'disabled'))):
        raise ValueError('actual CTest report did not pass the declared public probe')


def inspect_probe(profile, report_dir, *, receiver):
    """Re-evaluate complete retained captures, without recreating any command.

    This is environment smoke evidence, not a project acceptance result. The
    original probe.json and every raw record stay byte-for-byte unchanged.
    """
    report = Path(report_dir).resolve()
    original = json.loads((report / 'probe.json').read_text(encoding='utf-8'))
    result = {'status': 'ERROR', 'complete': False, 'operation': 'probe',
              'profile_sha256': runtime.profile_digest(profile), 'receiver': receiver,
              'source_report': str(report / 'probe.json'), 'issues': [], 'operations': [],
              'observations_complete': profile['extensions']['qt']['dependency_observation'] == 'OBSERVED_SELECTED_CLOSURE'}
    try:
        if original.get('profile_sha256') != result['profile_sha256'] or original.get('receiver') != receiver:
            raise ValueError('retained probe profile/receiver differs; old evidence is not current evidence')
        if [row.get('operation') for row in original.get('operations', [])] != ['configure', 'build', 'test', 'run']:
            raise ValueError('probe has not captured all declared operations')
        for row in original['operations']:
            operation = row['operation']
            directory = report / operation
            if Path(row['path']).resolve() != directory:
                raise ValueError('retained operation path is not this probe report')
            record = runtime.read_capture(directory)
            if (record.get('status') != 'FINISHED' or record.get('returncode') != 0
                    or record.get('metadata', {}).get('operation') != operation
                    or record.get('metadata', {}).get('package') != PACKAGE):
                raise ValueError('retained probe operation did not complete successfully: ' + operation)
            result['operations'].append({'operation': operation, 'path': str(directory), 'record': record})
        _check_probe_output(report)
        result.update(status='PASS', complete=True)
    except (OSError, ValueError, ET.ParseError) as error:
        result['issues'].append(str(error))
    return result


def parser():
    command = argparse.ArgumentParser(description=__doc__)
    sub = command.add_subparsers(dest='command', required=True)
    discover_cmd = sub.add_parser('discover')
    for name in ('python', 'cmake', 'ctest', 'output'):
        discover_cmd.add_argument('--' + name, required=True)
    discover_cmd.add_argument('--qt-sdk', action='append', required=True)
    discover_cmd.add_argument('--qmake')
    discover_cmd.add_argument('--otool')
    discover_cmd.add_argument('--compiler')
    discover_cmd.add_argument('--read-root', action='append', default=[])
    observe_cmd = sub.add_parser('observe')
    observe_cmd.add_argument('--profile', required=True)
    observe_cmd.add_argument('--report-dir', required=True)
    observe_cmd.add_argument('--output-profile', required=True)
    observe_cmd.add_argument('--adapt-loader-paths', action='store_true')
    observe_cmd.add_argument('--dependency-directory', action='append', default=[])
    probe_cmd = sub.add_parser('probe')
    for name in ('profile', 'work-dir', 'report-dir', 'receiver'):
        probe_cmd.add_argument('--' + name, required=True)
    inspect_cmd = sub.add_parser('inspect')
    for name in ('profile', 'report-dir', 'receiver'):
        inspect_cmd.add_argument('--' + name, required=True)
    return command


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'discover':
            tools = {'qt-python': args.python, 'cmake': args.cmake, 'ctest': args.ctest}
            tools.update({key: getattr(args, key) for key in ('qmake', 'otool', 'compiler') if getattr(args, key)})
            result = discover(tools, args.qt_sdk, read_paths=args.read_root)
            runtime.write_new_json(args.output, result['profile'] if result['profile'] else result)
        elif args.command == 'observe':
            if Path(args.output_profile).exists():
                raise FileExistsError('output profile exists; preserve previous bindings')
            result = observe(load_profile(args.profile), args.report_dir,
                adapt_loader_paths=args.adapt_loader_paths, dependency_directories=args.dependency_directory)
            if result['profile']:
                runtime.write_new_json(args.output_profile, result['profile'])
        elif args.command == 'inspect':
            result = inspect_probe(load_profile(args.profile), args.report_dir, receiver=args.receiver)
        else:
            result = probe(load_profile(args.profile), args.work_dir, args.report_dir, receiver=args.receiver)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['status'] in ('READY', 'OBSERVED', 'PASS') else 2
    except (OSError, ValueError) as error:
        print(json.dumps({'status': 'ERROR', 'issues': [str(error)]}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
