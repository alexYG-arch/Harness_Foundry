"""Public stack environment format v1 and single-command capture.

No installation, retries, permission grants or controller state. Copy this file
unchanged into selected packages and protected checker bundles. Profiles contain
only explicitly selected, non-secret configuration; never dump the parent env.
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import stat
import subprocess
import time


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _absolute(value):
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        raise ValueError('expected an absolute invocation path')
    if any(ord(c) < 32 for c in value):
        raise ValueError('path contains control characters')
    # Normalize parents, preserving a venv executable's final alias.
    return str(Path(value).parent.resolve() / Path(value).name)


def file_observation(path):
    path = _absolute(str(path))
    try:
        file = Path(path)
        resolved = file.resolve(strict=True)
        if not resolved.is_file():
            raise ValueError('only explicitly selected files can be observed')
        digest = hashlib.sha256()
        with file.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        return {'path': path, 'resolved_path': str(resolved), 'status': 'OBSERVED',
                'size': resolved.stat().st_size, 'sha256': digest.hexdigest()}
    except (OSError, RuntimeError, ValueError) as exc:
        return {'path': path, 'status': 'UNAVAILABLE', 'error': type(exc).__name__}



def alias_observation(path):
    """Read one declared link, including a retargeted or no-longer-link path."""
    value = str(path)
    if not Path(value).is_absolute() or any(ord(c) < 32 for c in value):
        raise ValueError('alias observation requires an absolute path')
    link = Path(value)
    result = {'path': str(link), 'status': 'UNAVAILABLE'}
    try:
        result['read_parent'] = str(link.parent.resolve(strict=True))
        info = link.lstat()
        if not stat.S_ISLNK(info.st_mode):
            result.update(status='OBSERVED', link_target=None, resolved_path=str(link.resolve(strict=True)))
        else:
            result['link_target'] = os.readlink(link)
            result.update(status='OBSERVED', resolved_path=str(link.resolve(strict=True)))
    except (OSError, RuntimeError, ValueError) as exc:
        result['error'] = type(exc).__name__
    return result


def make_profile(package, tools, *, environment=None, operations=(), observe_paths=(),
                 read_paths=(), extensions=None):
    """Pure file/path preparation; tool versions are not executed here."""
    tools = {role: _absolute(path) for role, path in tools.items()}
    paths = list(dict.fromkeys([*tools.values(), *(_absolute(str(p)) for p in observe_paths)]))
    profile = {'kind': 'stack-environment-profile', 'format_version': 1,
               'package': dict(package), 'platform': {'system': platform.system(), 'machine': platform.machine()},
               'tools': tools, 'environment': environment or {'set': {}, 'prepend': {}},
               'operations': list(operations), 'observations': [file_observation(p) for p in paths],
               'read_paths': list(dict.fromkeys(_absolute(str(p)) for p in read_paths)),
               'extensions': extensions or {}}
    validate_profile(profile)
    return profile


def validate_profile(profile, expected_package=None):
    if not isinstance(profile, dict) or profile.get('kind') != 'stack-environment-profile' or profile.get('format_version') != 1:
        raise ValueError('unsupported stack environment profile format')
    package = profile.get('package', {})
    if not isinstance(package, dict) or not all(isinstance(package.get(k), str) and package[k] for k in ('name', 'version')):
        raise ValueError('profile requires package name and version')
    if expected_package is not None:
        expected = expected_package if isinstance(expected_package, dict) else dict(zip(('name', 'version'), expected_package))
        if any(package.get(k) != expected.get(k) for k in ('name', 'version')):
            raise ValueError('profile package/version mismatch')
    system = profile.get('platform')
    if not isinstance(system, dict) or not all(isinstance(system.get(k), str) and system[k] for k in ('system', 'machine')):
        raise ValueError('profile requires observed platform system and machine')
    tools = profile.get('tools')
    if not isinstance(tools, dict) or not tools:
        raise ValueError('profile requires selected tools')
    for role, path in tools.items():
        if not isinstance(role, str) or not role:
            raise ValueError('invalid tool role')
        _absolute(path)
    env = profile.get('environment')
    if not isinstance(env, dict) or set(env) - {'set', 'prepend'}:
        raise ValueError('environment supports set and prepend only')
    for operation in ('set', 'prepend'):
        values = env.get(operation, {})
        if not isinstance(values, dict):
            raise ValueError('environment operation must be an object')
        for key, value in values.items():
            if not isinstance(key, str) or not key or '=' in key or '\0' in key:
                raise ValueError('invalid environment key')
            if operation == 'set':
                valid = isinstance(value, str) and '\0' not in value
            else:
                valid = isinstance(value, list) and all(isinstance(v, str) and v and '\0' not in v for v in value)
            if not valid:
                raise ValueError('invalid environment value: ' + key)
    if set(env.get('set', {})) & set(env.get('prepend', {})):
        raise ValueError('same environment key has conflicting operations')
    if not isinstance(profile.get('operations'), list) or not all(isinstance(x, str) and x for x in profile['operations']):
        raise ValueError('operations must be explicit strings')
    observations = profile.get('observations')
    if not isinstance(observations, list):
        raise ValueError('observations must be an explicit list')
    paths = []
    for observation in observations:
        if not isinstance(observation, dict):
            raise ValueError('invalid observation')
        paths.append(_absolute(observation.get('path')))
    if len(paths) != len(set(paths)) or not set(_absolute(p) for p in tools.values()).issubset(paths):
        raise ValueError('observations must uniquely include selected tools')
    return profile


def load_profile(path, expected_package=None):
    return validate_profile(json.loads(Path(path).read_text(encoding='utf-8')), expected_package)


def profile_digest(profile):
    validate_profile(profile)
    return hashlib.sha256(_json(profile).encode()).hexdigest()


def tool(profile, role):
    validate_profile(profile)
    if role not in profile['tools']:
        raise ValueError('unbound tool role: ' + role)
    return _absolute(profile['tools'][role])


def child_environment(profile, inherited=None):
    validate_profile(profile)
    env = dict(os.environ if inherited is None else inherited)
    changes = profile['environment']
    env.update(changes.get('set', {}))
    for key, paths in changes.get('prepend', {}).items():
        # Do not resolve paths or collapse venv aliases while merging PATH.
        old = env.get(key, '').split(os.pathsep) if env.get(key) else []
        env[key] = os.pathsep.join(dict.fromkeys([*paths, *old]))
    return env


def write_new_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def _save_capture(path, record):
    # Only the invocation file in this newly owned directory is updated.
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run_capture(argv, cwd, report_dir, env=None, timeout=900, metadata=None):
    """One explicit child call, no retries; the enclosing host owns authority.

    Timeout kills this process group. The record cannot establish independent
    acceptance, effective sandbox rights or a controller attempt by itself.
    """
    if not isinstance(argv, (list, tuple)) or not argv or not all(isinstance(v, str) and '\0' not in v for v in argv):
        raise ValueError('argv must contain strings')
    _absolute(argv[0])
    cwd = _absolute(str(cwd))
    if not Path(cwd).is_dir() or not isinstance(timeout, (int, float)) or not 0 < timeout <= 86400:
        raise ValueError('existing cwd and positive finite timeout required')
    report = Path(report_dir)
    report.mkdir(parents=True, exist_ok=False)
    record = {'format_version': 1, 'kind': 'stack-command-capture', 'status': 'STARTED',
              'complete': False, 'argv': list(argv), 'cwd': cwd, 'timeout_seconds': timeout,
              'metadata': metadata or {}, 'started_at': time.time(), 'commands_executed': False,
              'stdout': 'stdout.txt', 'stderr': 'stderr.txt'}
    invocation = report / 'invocation.json'
    _save_capture(invocation, record)
    child = None
    started = time.monotonic()
    try:
        with (report / 'stdout.txt').open('wb') as stdout, (report / 'stderr.txt').open('wb') as stderr:
            child = subprocess.Popen(list(argv), cwd=cwd, env=env, stdout=stdout, stderr=stderr,
                                     start_new_session=True)
            record.update(pid=child.pid, commands_executed=True)
            _save_capture(invocation, record)
            try:
                record.update(returncode=child.wait(timeout=timeout), status='FINISHED')
            except subprocess.TimeoutExpired:
                record.update(status='TIMEOUT')
    except (OSError, ValueError) as exc:
        record.update(status='ERROR', error=type(exc).__name__)
    finally:
        if child is not None:
            # Include descendants left behind by a completed finite command.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError as exc:
                record.update(status='ERROR', cleanup_error=type(exc).__name__, cleanup_unresolved=True)
            try:
                record['returncode'] = child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                record.update(status='ERROR', cleanup_error='TimeoutExpired', cleanup_unresolved=True)
        record.update(elapsed_seconds=time.monotonic() - started, finished_at=time.time(),
                      complete=not record.get('cleanup_unresolved', False)
                               and record['status'] in ('FINISHED', 'ERROR', 'TIMEOUT'))
        _save_capture(invocation, record)
    return record


def read_capture(report_dir):
    """Read captured evidence; never launch, recreate or repair a command."""
    report = Path(report_dir)
    record = json.loads((report / 'invocation.json').read_text(encoding='utf-8'))
    if (record.get('kind') != 'stack-command-capture' or record.get('format_version') != 1
            or record.get('complete') is not True or record.get('status') not in ('FINISHED', 'ERROR', 'TIMEOUT')
            or record.get('stdout') != 'stdout.txt' or record.get('stderr') != 'stderr.txt'
            or not all((report / p).is_file() for p in ('stdout.txt', 'stderr.txt'))
            or record.get('status') == 'FINISHED' and not isinstance(record.get('returncode'), int)):
        raise ValueError('capture is incomplete; status is unknown, no command was replayed')
    return record


def reuse_probe(profile, report, receiver):
    """Compare declared evidence only. No process, retry, cache or authority."""
    validate_profile(profile)
    if not isinstance(report, dict) or report.get('status') != 'PASS' or report.get('complete') is not True:
        return {'decision': 'UNKNOWN', 'reason': 'no complete successful probe'}
    if not receiver or report.get('receiver') != receiver:
        return {'decision': 'REPROBE', 'reason': 'receiver conditions differ or are unbound'}
    if profile.get('platform') != {'system': platform.system(), 'machine': platform.machine()}:
        return {'decision': 'REPROBE', 'reason': 'platform changed'}
    if report.get('profile_sha256') != profile_digest(profile):
        return {'decision': 'REPROBE', 'reason': 'profile changed'}
    if report.get('operation') not in profile['operations']:
        return {'decision': 'UNKNOWN', 'reason': 'probe operation is not bound'}
    extra = report.get('observations', [])
    if not isinstance(extra, list) or not all(isinstance(row, dict) and isinstance(row.get('path'), str) for row in extra):
        return {'decision': 'UNKNOWN', 'reason': 'probe observations are incomplete'}
    for old in [*profile['observations'], *extra]:
        current = file_observation(old['path'])
        if old.get('status') != 'OBSERVED' or current.get('status') != 'OBSERVED':
            return {'decision': 'UNKNOWN', 'reason': 'declared dependency could not be observed', 'path': old['path']}
        if old != current:
            return {'decision': 'REPROBE', 'reason': 'declared dependency changed', 'path': old['path']}
    aliases = profile.get('extensions', {}).get('path_aliases', [])
    if not isinstance(aliases, list):
        return {'decision': 'UNKNOWN', 'reason': 'declared alias observations are incomplete'}
    for old in aliases:
        if not isinstance(old, dict) or not isinstance(old.get('path'), str):
            return {'decision': 'UNKNOWN', 'reason': 'declared alias observations are incomplete'}
        try:
            current = alias_observation(old['path'])
        except (OSError, RuntimeError, ValueError):
            return {'decision': 'UNKNOWN', 'reason': 'declared alias could not be observed', 'path': old['path']}
        # A readable changed link remains a change even if its new target is missing.
        if ('link_target' in current and 'link_target' in old
                and current['link_target'] != old['link_target']):
            return {'decision': 'REPROBE', 'reason': 'declared alias changed', 'path': old['path']}
        if old.get('status') != 'OBSERVED' or current.get('status') != 'OBSERVED':
            return {'decision': 'UNKNOWN', 'reason': 'declared alias could not be observed', 'path': old['path']}
        if old != current:
            return {'decision': 'REPROBE', 'reason': 'declared alias changed', 'path': old['path']}
    if report.get('observations_complete') is False:
        return {'decision': 'UNKNOWN', 'reason': 'relevant dependency observations are incomplete'}
    return {'decision': 'REUSE', 'reason': 'declared operation dependencies and receiver still match'}
