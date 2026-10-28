"""Observe a selected Mach-O dependency closure without scanning an installation.

This helper supplies observations and path proposals only. The caller owns
permissions, environment selection, acceptance, retries and cleanup of evidence.
"""
import importlib.util
from pathlib import Path
import re
import stat


def _runtime():
    path = Path(__file__).resolve().with_name('stack_runtime.py')
    spec = importlib.util.spec_from_file_location('_native_dependency_runtime', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _selected_path(path, aliases, read_path_proposals, runtime):
    """Resolve only this selected path, retaining the links actually traversed."""
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('selected dependency path must be absolute')
    current, pending = Path(path.anchor), list(path.parts[1:])
    while pending:
        part = pending.pop(0)
        if part == '..':
            current = current.parent
            continue
        node = current / part
        info = node.lstat()
        if stat.S_ISLNK(info.st_mode):
            row = runtime.alias_observation(node)
            if row not in aliases:
                if any(old['path'] == row['path'] for old in aliases):
                    raise ValueError('selected alias changed during observation: ' + str(node))
                aliases.append(row)
            parent = str(current)
            if parent not in read_path_proposals:
                read_path_proposals.append(parent)
            if row['status'] != 'OBSERVED':
                raise ValueError('selected alias is unavailable: ' + str(node) + ' (' + row.get('error', 'unknown') + ')')
            target = Path(row['link_target'])
            if target.is_absolute():
                current = Path(target.anchor)
                pending = list(target.parts[1:]) + pending
            else:
                pending = list(target.parts) + pending
        else:
            current = node
    return current


def dependency_path(raw, owner, directories, *, aliases=None, read_path_proposals=None, runtime=None):
    aliases = [] if aliases is None else aliases
    read_path_proposals = [] if read_path_proposals is None else read_path_proposals
    runtime = runtime or _runtime()
    if raw.startswith(('/usr/lib/', '/System/Library/')):
        return None  # macOS dyld-cache system entries need not be loose files.
    if raw.startswith('@loader_path/'):
        selected = Path(owner).parent / raw[len('@loader_path/'):]
    elif raw.startswith('@rpath/'):
        suffix = raw[len('@rpath/'):]
        candidates = [Path(root) / suffix for root in directories if (Path(root) / suffix).is_file()]
        found = {str(path.resolve(strict=True)) for path in candidates}
        if len(found) != 1:
            raise ValueError('unresolved or ambiguous @rpath dependency: ' + raw)
        selected = candidates[0]
    elif raw.startswith('/'):
        selected = Path(raw)
    else:
        raise ValueError('unresolved load dependency: ' + raw)
    return _selected_path(selected, aliases, read_path_proposals, runtime)


def discover_dependencies(initial_files, *, tool, report_dir, environment,
                          dependency_directories=(), timeout=900, metadata=None,
                          runtime=None):
    """Run one recorded otool call per selected non-system dependency.

    The helper creates a fresh report root. Existing report paths are never
    overwritten. It returns partial observations with ERROR for missing or
    ambiguous dependencies; no fallback install, permission change or retry.
    """
    runtime = runtime or _runtime()
    report = Path(report_dir).resolve()
    report.mkdir(parents=True, exist_ok=False)
    result = {'status': 'ERROR', 'complete': False, 'files': [], 'library_dirs': [],
              'framework_dirs': [], 'operations': [], 'issues': [], 'aliases': [], 'read_path_proposals': []}
    try:
        if not initial_files:
            raise ValueError('select at least one actual native file to observe')
        if not Path(tool).is_absolute():
            raise ValueError('explicit absolute dependency tool path required')
        pending, seen = list(map(Path, initial_files)), set()
        while pending:
            item = pending.pop(0)
            if not item.is_absolute() or not item.is_file():
                raise ValueError('selected native file unavailable: ' + str(item))
            item = _selected_path(item, result['aliases'], result['read_path_proposals'], runtime)
            if str(item) in seen:
                continue
            seen.add(str(item))
            directory = report / ('dependency-' + str(len(seen)))
            record = runtime.run_capture([str(tool), '-L', str(item)], cwd=str(report),
                report_dir=str(directory), env=environment, timeout=timeout,
                metadata={'operation': 'observe-native-dependency', **(metadata or {})})
            result['operations'].append({'operation': 'dependency', 'path': str(directory), 'record': record})
            if record.get('status') != 'FINISHED' or record.get('returncode') != 0:
                raise ValueError('dependency query failed; inspect ' + str(directory))
            output = (directory / 'stdout.txt').read_text(encoding='utf-8', errors='replace')
            lines = output.splitlines()
            if not lines or not lines[0].rstrip().endswith(':'):
                raise ValueError('dependency tool did not report a Mach-O file header')
            observation = runtime.file_observation(str(item))
            if observation.get('status') != 'OBSERVED':
                raise ValueError('selected dependency could not be read: ' + str(item))
            result['files'].append(observation)
            if '.framework/' in str(item):
                framework = str(item).split('.framework/', 1)[0] + '.framework'
                value = str(Path(framework).parent)
                if value not in result['framework_dirs']:
                    result['framework_dirs'].append(value)
            elif str(item.parent) not in result['library_dirs']:
                result['library_dirs'].append(str(item.parent))
            for line in lines[1:]:
                match = re.match(r'\s+(.+?) \(compatibility version ', line)
                if not match:
                    if line.strip():
                        raise ValueError('unrecognized otool dependency line: ' + line)
                    continue
                dependency = dependency_path(match.group(1), item, dependency_directories,
                    aliases=result['aliases'], read_path_proposals=result['read_path_proposals'], runtime=runtime)
                if dependency is not None and dependency != item:
                    pending.append(dependency)
        result.update(status='OBSERVED', complete=True)
    except (OSError, RuntimeError, ValueError) as error:
        result['issues'].append(str(error))
    runtime.write_new_json(report / 'dependencies.json', result)
    return result
