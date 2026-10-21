"""One explicit CMake/CTest invocation with a bound Qt environment profile."""
import argparse
import importlib.util
import json
from pathlib import Path


def _load():
    path = Path(__file__).resolve().with_name('qt_environment.py')
    spec = importlib.util.spec_from_file_location('_qt_environment_bridge', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


qt_environment = _load()
runtime = qt_environment.runtime


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest='command', required=True)
    for name in ('configure', 'build', 'test'):
        command = commands.add_parser(name)
        command.add_argument('--profile', required=True)
        command.add_argument('--build-dir', required=True)
        command.add_argument('--report-dir', required=True)
        command.add_argument('--timeout', type=float, default=900)
        command.add_argument('--config')
        command.add_argument('--ctest' if name == 'test' else '--cmake')
        if name == 'configure':
            command.add_argument('--source', required=True)
            command.add_argument('--generator')
            command.add_argument('--preset')
            command.add_argument('--define', action='append', default=[])
        elif name == 'build':
            command.add_argument('--target', action='append', default=[])
        else:
            command.add_argument('--test-regex')
    return result


def run(arguments):
    profile = qt_environment.load_profile(arguments.profile)
    role = 'ctest' if arguments.command == 'test' else 'cmake'
    tool = runtime.tool(profile, role)
    explicit = getattr(arguments, role, None)
    if explicit is not None and str(Path(explicit).parent.resolve() / Path(explicit).name) != tool:
        raise ValueError('explicit tool differs from bound profile: ' + role)
    build = Path(arguments.build_dir).resolve()
    report = Path(arguments.report_dir).resolve()
    if report.exists():
        raise FileExistsError('report directory exists; read retained evidence instead of replaying')
    if arguments.command == 'configure':
        source = Path(arguments.source).resolve(strict=True)
        if not source.is_dir() or build == source:
            raise ValueError('source must be a directory and build must be separate')
        argv = [tool, '-S', str(source), '-B', str(build)]
        if arguments.preset:
            argv.extend(['--preset', arguments.preset])
        if arguments.generator:
            argv.extend(['-G', arguments.generator])
        if arguments.config:
            argv.append('-DCMAKE_BUILD_TYPE=' + arguments.config)
        argv.extend('-D' + value for value in qt_environment.configure_definitions(profile, arguments.define))
        build.mkdir(parents=True, exist_ok=True)
        cwd = source if arguments.preset else build
    elif arguments.command == 'build':
        argv = [tool, '--build', str(build)]
        if arguments.config:
            argv.extend(['--config', arguments.config])
        if arguments.target:
            argv.extend(['--target', *arguments.target])
        cwd = build
    else:
        argv = [tool, '--test-dir', str(build), '--output-on-failure', '--no-tests=error',
                '--output-junit', str(report / 'junit.xml')]
        if arguments.config:
            argv.extend(['-C', arguments.config])
        if arguments.test_regex:
            argv.extend(['-R', arguments.test_regex])
        cwd = build
    if not cwd.is_dir():
        raise ValueError('build directory does not exist')
    return runtime.run_capture(argv, cwd=str(cwd), report_dir=str(report),
        env=qt_environment.environment(profile), timeout=arguments.timeout,
        metadata={'operation': arguments.command, 'package': qt_environment.PACKAGE,
            'profile_sha256': runtime.profile_digest(profile),
            'configured_environment': profile['environment']})


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        record = run(args)
        print(json.dumps(record))
        return 0 if record.get('returncode') == 0 and record['status'] == 'FINISHED' else 1 if record['status'] == 'FINISHED' else 2
    except (OSError, ValueError) as error:
        print(json.dumps({'status': 'ERROR', 'issues': [str(error)]}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
