"""Independent fixture checks; stdout is diagnostic, never controller acceptance.

The caller supplies a fixed expectation outside the target write root. Live HTTP
is an explicit mode; ordinary-process tests do not establish S4 Build acceptance.
Offline mode neither creates sockets nor opens URLs.
"""
import argparse
import errno
from http.client import HTTPConnection
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import uuid


DOC_CLI_RUNNER = '''import json, os, runpy, sys
sys.argv = sys.argv[1:]
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
except OSError as error:
    filename = os.path.abspath(os.fsdecode(error.filename)) if error.filename is not None else None
    print("\\n" + json.dumps({"doc_cli_error": "OSError", "errno": error.errno,
                             "error_type": type(error).__name__, "filename": filename,
                             "message": str(error)}), file=sys.stderr)
    raise SystemExit(1)
'''


def load_module(path):
    spec = importlib.util.spec_from_file_location('fixture_' + uuid.uuid4().hex, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def check_doc(target, expected, *, scratch=None):
    target = Path(target).resolve()
    # Resource callers supply their approved scratch. Standalone fixture checks
    # own a temporary directory; neither route writes into the product.
    with tempfile.TemporaryDirectory(prefix='doc-export-', dir=scratch) as temporary:
        output = Path(temporary).resolve()/'report.md'
        completed = subprocess.run([sys.executable, '-I', '-B', '-c', DOC_CLI_RUNNER, str(target/'tools/render.py'),
            '--root', str(target), '--output', str(output)], cwd=target, capture_output=True)
        if completed.returncode < 0:
            raise RuntimeError('document CLI was terminated by a signal')
        if completed.returncode:
            try:
                error = json.loads(completed.stderr.splitlines()[-1])
            except (json.JSONDecodeError, UnicodeError, IndexError):
                error = None
            if isinstance(error, dict) and error.get('doc_cli_error') == 'OSError':
                filename = error.get('filename')
                # Only identifiable product path/layout errors are repairable.
                # Scratch, missing attribution and other OS failures stay ERROR.
                if error.get('errno') in (errno.ENOENT, errno.ENOTDIR, errno.EISDIR) and isinstance(filename, str):
                    path = Path(filename)
                    if path.is_absolute() and path.resolve().is_relative_to(target):
                        raise AssertionError('document CLI product path error ('
                            + error['error_type'] + '): ' + error['message'])
                raise OSError(error['errno'], error['message'])
        assert completed.returncode == 0, ('document CLI failed: '
            + completed.stderr.decode('utf-8', errors='replace'))
        assert output.is_file(), 'document CLI did not create its declared output'
        actual = output.read_bytes().decode('utf-8')
    assert isinstance(actual, str) and actual.splitlines(), 'renderer must return nonempty document text'
    assert actual.splitlines()[0] == '# ' + expected['title'], 'custom document title was lost'
    headings = [line[3:] for line in actual.splitlines() if line.startswith('## ')]
    assert headings == expected['ordered_headings'] + ['Sources'], 'custom headings or section order was changed'
    section_lines = {}
    active = None
    for line in actual.splitlines()[1:]:
        if line.startswith('## '):
            active = line[3:]
            section_lines[active] = []
        elif active is not None:
            section_lines[active].append(line)
        elif line.strip():
            raise AssertionError('unexpected content before first document section')
    for title, required in expected['section_lines'].items():
        content = [line for line in section_lines[title] if line.strip()]
        assert content == required, 'wrong fact, source or priority in section: ' + title
    source_lines = [line for line in section_lines['Sources'] if line.strip()]
    expected_sources = [f"- [{ident}] " + (source['title'] + ' — ' if expected.get('source_titles', True) else '') + source['locator']
                        for ident, source in expected['sources'].items()]
    assert sorted(source_lines) == sorted(expected_sources), 'source reference mapping changed'
    for token in expected['required_facts'] + expected['citations'] + expected['priorities']:
        assert token in actual, 'missing required fact, citation or feature: ' + token
    assert (target / 'USER_NOTES.md').read_bytes() == expected['user_notes'].encode('utf-8'), 'user notes changed'
    return {'kind':'DOC', 'scope':'offline-cli-exported-content', 'result':'PASS'}


def check_api(target, expected, *, live=False, service_state=None):
    service_state = {} if service_state is None else service_state
    service_state.update(services_started=False, services_stopped=True, phase='TARGET_CONTRACT')
    target = Path(target)
    service = load_module(target / 'tools/service.py')
    client = load_module(target / 'tools/client.py')
    config = read_json(target / 'config.json')
    items = read_json(target / 'data/items.json')
    assert isinstance(config, dict) and 'timeout' in config, 'target config must declare its timeout'
    assert config['timeout'] == expected['timeout'], 'user timeout changed'
    assert items == expected['items'], 'fixture data changed'
    responses = [('/health',200,expected['health']), ('/items',200,{'items':expected['items']}), ('/unknown',404,expected['not_found'])]
    for path, status, value in responses:
        assert service.response(path, items) == (status, value), 'API behavior changed: ' + path

    class RecordedOpener:
        def __init__(self):
            self.calls = []
        def open(self, url, *, timeout):
            self.calls.append((url, timeout))
            return io.BytesIO(json.dumps({'items': expected['items']}).encode('utf-8'))

    opener = RecordedOpener()
    assert client.request('http://127.0.0.1:1', '/items', config, opener) == {'items': expected['items']}
    assert opener.calls == [('http://127.0.0.1:1/items', expected['timeout'])], 'client does not use its configured timeout'
    if not live:
        return {'kind':'API', 'scope':'offline-handler-and-client-contract', 'result':'PASS', 'live_http':'NOT_RUN'}

    service_state['services_stopped'] = False
    service_state['phase'] = 'SERVICE_STARTUP'
    server = service.make_server(items)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    started = False
    try:
        worker.start()
        started = True
        service_state['services_started'] = True
        service_state['phase'] = 'TARGET_CONTRACT'
        assert server.server_address[0] == '127.0.0.1', 'service did not bind loopback'
        base = 'http://127.0.0.1:' + str(server.server_port)
        assert client.request(base, '/health', config) == expected['health']
        assert client.request(base, '/items', config) == {'items': expected['items']}
        http = HTTPConnection('127.0.0.1', server.server_port, timeout=config['timeout'])
        try:
            for path, status, value in responses:
                http.request('GET', path)
                with http.getresponse() as response:
                    assert response.status == status, 'HTTP status changed: ' + path
                    assert json.loads(response.read().decode('utf-8')) == value, 'HTTP body changed: ' + path
        finally:
            http.close()
    finally:
        previous_phase = service_state['phase']
        service_state['phase'] = 'SERVICE_CLEANUP'
        cleanup_errors = []
        operations = ([server.shutdown] if started else []) + [server.server_close]
        if started:
            operations.append(lambda: worker.join(timeout=5))
        for operation in operations:
            try:
                operation()
            except Exception as error:
                cleanup_errors.append(str(error))
        stopped = not worker.is_alive() and server.socket.fileno() == -1
        service_state['services_stopped'] = stopped and not cleanup_errors
        if not service_state['services_stopped']:
            raise RuntimeError('owned service cleanup failed: ' + '; '.join(cleanup_errors or ['listener or thread remains active']))
        service_state['phase'] = previous_phase
    return {'kind':'API', 'scope':'loopback-http-and-owned-service-cleanup', 'result':'PASS'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--kind', choices=['doc','api'], required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--expected', type=Path, required=True)
    parser.add_argument('--live-api', action='store_true')
    args = parser.parse_args()
    if args.live_api and args.kind != 'api':
        parser.error('--live-api only applies to API')
    expected = read_json(args.expected)
    result = check_doc(args.target, expected) if args.kind == 'doc' else check_api(args.target, expected, live=args.live_api)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
