"""One explicit CMake or CTest invocation; no scheduler, retries or installation."""

import argparse
import json
import os
from pathlib import Path
import subprocess


def executable(value):
    path = Path(value)
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError('supply an existing absolute executable path')
    # Keep the invocation path, including its terminal link.
    return str(path)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest='command', required=True)
    for name in ('configure', 'build', 'test'):
        command = commands.add_parser(name)
        command.add_argument('--build-dir', required=True)
        command.add_argument('--report-dir', required=True)
        command.add_argument('--config')
        command.add_argument('--ctest' if name == 'test' else '--cmake', required=True)
        if name == 'configure':
            command.add_argument('--source', required=True)
            command.add_argument('--generator')
            command.add_argument('--define', action='append', default=[])
        elif name == 'build':
            command.add_argument('--target', action='append', default=[])
        else:
            command.add_argument('--test-regex')
    return result


def run(arguments):
    build = Path(arguments.build_dir).resolve()
    report = Path(arguments.report_dir).resolve()
    if arguments.command == 'configure':
        source = Path(arguments.source).resolve(strict=True)
        if not source.is_dir():
            raise ValueError('source must be a directory')
        if build == source:
            raise ValueError('use a separate build directory')
        argv = [executable(arguments.cmake), '-S', str(source), '-B', str(build)]
        if arguments.generator:
            argv.extend(['-G', arguments.generator])
        if arguments.config:
            argv.append('-DCMAKE_BUILD_TYPE=' + arguments.config)
        for definition in arguments.define:
            if '=' not in definition or not definition.split('=', 1)[0]:
                raise ValueError('--define requires NAME[:TYPE]=VALUE')
            argv.append('-D' + definition)
    elif arguments.command == 'build':
        argv = [executable(arguments.cmake), '--build', str(build)]
        if arguments.config:
            argv.extend(['--config', arguments.config])
        if arguments.target:
            argv.extend(['--target', *arguments.target])
    else:
        argv = [executable(arguments.ctest), '--test-dir', str(build),
                '--output-on-failure', '--no-tests=error', '--output-junit', str(report / 'junit.xml')]
        if arguments.config:
            argv.extend(['-C', arguments.config])
        if arguments.test_regex:
            argv.extend(['-R', arguments.test_regex])
    if arguments.command != 'configure' and not build.is_dir():
        raise ValueError('build directory does not exist')
    # A caller selects a fresh evidence directory for each authorized command.
    # Refusing an existing one preserves old evidence and never triggers replay.
    report.mkdir(parents=True, exist_ok=False)
    if arguments.command == 'configure':
        build.mkdir(parents=True, exist_ok=True)
    record = {'schema_version': '1', 'command': arguments.command, 'status': 'STARTED',
              'argv': argv, 'cwd': str(build), 'build_dir': str(build), 'report_dir': str(report)}
    record_path = report / 'invocation.json'
    record_path.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    try:
        with (report / 'stdout.log').open('wb') as stdout, (report / 'stderr.log').open('wb') as stderr:
            completed = subprocess.run(argv, cwd=build, stdout=stdout, stderr=stderr, check=False)
        record.update(status='FINISHED', returncode=completed.returncode)
    except OSError as error:
        record.update(status='ERROR', error_type=type(error).__name__, error=str(error))
    record_path.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    return record


def main(argv=None):
    arguments = parser().parse_args(argv)
    try:
        record = run(arguments)
    except (OSError, ValueError) as error:
        print(json.dumps({'status': 'ERROR', 'error': str(error)}))
        return 2
    print(json.dumps(record))
    # A successful command is not an independent acceptance verdict.
    return 0 if record.get('returncode') == 0 else 1 if record['status'] == 'FINISHED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
