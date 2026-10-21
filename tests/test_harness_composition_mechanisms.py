"""Fixed DOC/API checks with isolated loopback HTTP; no Build/controller runs."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'examples/harness-composition-upgrade'
SPEC = importlib.util.spec_from_file_location('mechanism_checks', ROOT / 'verifier/check_mechanisms.py')
CHECKS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKS)


class MechanismFixtureTests(unittest.TestCase):
    def test_manifest_state_references_are_real_bytes(self):
        for kind in ('doc','api'):
            for manifest in (ROOT/'mechanisms'/kind/'scenarios').glob('*/inputs.json'):
                for entry in json.loads(manifest.read_text())['files']:
                    for side in ('C','G','N'):
                        state = entry[side]
                        if state is not None and not state.get('missing'):
                            path = manifest.parent/state['file']
                            self.assertTrue(path.is_file(), str(path))
                            self.assertEqual(bool(path.stat().st_mode & 0o111), state['executable'])

    def test_reference_candidates_pass_without_network(self):
        with patch('socket.socket', side_effect=AssertionError('network is not part of S1/S2')):
            for version in (2,3):
                with self.subTest(version=version):
                    CHECKS.check_doc(ROOT/f'mechanisms/doc/expected/after-v{version}', CHECKS.read_json(ROOT/f'verifier/expectations/doc-v{version}.json'))
                    result = CHECKS.check_api(ROOT/f'mechanisms/api/expected/after-v{version}', CHECKS.read_json(ROOT/f'verifier/expectations/api-v{version}.json'))
                    self.assertEqual(result['live_http'],'NOT_RUN')
            CHECKS.check_doc(ROOT/'mechanisms/doc/expected/after-incremental', CHECKS.read_json(ROOT/'verifier/expectations/doc-incremental.json'))

    def test_standalone_doc_cli_owns_and_cleans_temporary_outputs(self):
        for stage in ('v1', 'v2', 'v3', 'incremental'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                scratch = root/'standalone-scratch'
                scratch.mkdir()
                target = root/'product'
                fixture = 'custom/current' if stage == 'v1' else 'expected/after-' + stage
                shutil.copytree(ROOT/'mechanisms/doc'/fixture, target)
                before = {str(path.relative_to(target)): path.read_bytes()
                          for path in target.rglob('*') if path.is_file()}
                with patch.object(CHECKS.tempfile, 'tempdir', str(scratch)):
                    result = CHECKS.check_doc(target, CHECKS.read_json(ROOT/f'verifier/expectations/doc-{stage}.json'))
                self.assertEqual(result['scope'], 'offline-cli-exported-content')
                self.assertEqual(list(scratch.iterdir()), [])
                self.assertEqual({str(path.relative_to(target)): path.read_bytes()
                                  for path in target.rglob('*') if path.is_file()}, before)

    def test_doc_independent_expectation_rejects_omission_order_and_notes(self):
        for mutation in ('fact','order','citation','note'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                target = Path(temp)/'target'
                shutil.copytree(ROOT/'mechanisms/doc/expected/after-v3',target)
                if mutation == 'fact':
                    (target/'data/notes.json').write_text('[]')
                elif mutation == 'citation':
                    notes = CHECKS.read_json(target/'data/notes.json')
                    notes[0]['source'], notes[1]['source'] = notes[1]['source'], notes[0]['source']
                    (target/'data/notes.json').write_text(json.dumps(notes))
                elif mutation == 'order':
                    config = CHECKS.read_json(target/'config.json'); config['sections'].reverse()
                    (target/'config.json').write_text(json.dumps(config))
                else:
                    (target/'USER_NOTES.md').write_text('overwritten')
                with self.assertRaises(AssertionError):
                    CHECKS.check_doc(target, CHECKS.read_json(ROOT/'verifier/expectations/doc-v3.json'))

    def test_doc_rejects_extra_facts_duplicate_lines_and_wrong_references(self):
        for stage in ('v1', 'v2', 'v3', 'incremental'):
            expected = CHECKS.read_json(ROOT/f'verifier/expectations/doc-{stage}.json')
            for title, lines in expected['section_lines'].items():
                line = lines[0]
                additions = {
                    'extra_fact': '- 未经来源支持的额外事实。 [s1]',
                    'duplicate_line': line,
                    'wrong_reference': line.replace('[s1]', '[s2]') if '[s1]' in line else line.replace('[s2]', '[s1]'),
                }
                for mutation, extra in additions.items():
                    with self.subTest(stage=stage, title=title, mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                        target = Path(temporary)/'product'
                        fixture = 'custom/current' if stage == 'v1' else 'expected/after-' + stage
                        shutil.copytree(ROOT/'mechanisms/doc'/fixture, target)
                        renderer = target/'tools/render.py'
                        code = renderer.read_text()
                        original = 'args.output.write_text(result, encoding="utf-8")'
                        self.assertIn(original, code)
                        # Keep the correct line and sources, then add an invalid
                        # body line through the real CLI's output path.
                        before, after = line + '\n', line + '\n' + extra + '\n'
                        renderer.write_text(code.replace(original,
                            f'args.output.write_text(result.replace({before!r}, {after!r}, 1), encoding="utf-8")'))
                        with self.assertRaisesRegex(AssertionError, 'wrong fact, source or priority in section: ' + title):
                            CHECKS.check_doc(target, expected)

    def test_doc_rejects_nonempty_content_before_first_section(self):
        for stage in ('v1', 'v2', 'v3', 'incremental'):
            expected = CHECKS.read_json(ROOT/f'verifier/expectations/doc-{stage}.json')
            line = next(iter(expected['section_lines'].values()))[0]
            additions = {
                'extra_fact': '- 未经来源支持的额外事实。 [s1]',
                'duplicate_line': line,
                'wrong_reference': line.replace('[s1]', '[s2]') if '[s1]' in line else line.replace('[s2]', '[s1]'),
            }
            for mutation, extra in additions.items():
                with self.subTest(stage=stage, mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    target, scratch = root/'product', root/'scratch'
                    scratch.mkdir()
                    fixture = 'custom/current' if stage == 'v1' else 'expected/after-' + stage
                    shutil.copytree(ROOT/'mechanisms/doc'/fixture, target)
                    renderer = target/'tools/render.py'
                    code = renderer.read_text()
                    original = 'args.output.write_text(result, encoding="utf-8")'
                    self.assertIn(original, code)
                    # Inject through the real CLI after the title; every
                    # expected section body and source remains intact.
                    before = '# ' + expected['title'] + '\n'
                    after = before + extra + '\n'
                    renderer.write_text(code.replace(original,
                        f'args.output.write_text(result.replace({before!r}, {after!r}, 1), encoding="utf-8")'))
                    with self.assertRaisesRegex(AssertionError, '^unexpected content before first document section$'):
                        CHECKS.check_doc(target, expected, scratch=scratch)
                    self.assertEqual(list(scratch.iterdir()), [])

    def test_doc_allows_blank_variations_only_before_first_section(self):
        for stage in ('v1', 'v2', 'v3', 'incremental'):
            expected = CHECKS.read_json(ROOT/f'verifier/expectations/doc-{stage}.json')
            for name, gap in (('no_blank_line', ''), ('whitespace_lines', '\n \t\n\n')):
                with self.subTest(stage=stage, whitespace=name), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    target, scratch = root/'product', root/'scratch'
                    scratch.mkdir()
                    fixture = 'custom/current' if stage == 'v1' else 'expected/after-' + stage
                    shutil.copytree(ROOT/'mechanisms/doc'/fixture, target)
                    renderer = target/'tools/render.py'
                    code = renderer.read_text()
                    original = 'args.output.write_text(result, encoding="utf-8")'
                    self.assertIn(original, code)
                    title = '# ' + expected['title'] + '\n'
                    first = '## ' + expected['ordered_headings'][0]
                    before, after = title + '\n' + first, title + gap + first
                    renderer.write_text(code.replace(original,
                        f'args.output.write_text(result.replace({before!r}, {after!r}, 1), encoding="utf-8")'))
                    result = CHECKS.check_doc(target, expected, scratch=scratch)
                    self.assertEqual(result['scope'], 'offline-cli-exported-content')
                    self.assertEqual(result['result'], 'PASS')
                    self.assertEqual(list(scratch.iterdir()), [])

    def test_doc_allows_blank_and_whitespace_only_lines(self):
        transformations = {
            'remove_blank_lines': '"\\n".join(line for line in result.splitlines() if line.strip()) + "\\n"',
            'add_whitespace_lines': 'result.replace("\\n", "\\n \\t\\n\\n")',
        }
        for stage in ('v1', 'v2', 'v3', 'incremental'):
            for name, expression in transformations.items():
                with self.subTest(stage=stage, whitespace=name), tempfile.TemporaryDirectory() as temporary:
                    target = Path(temporary)/'product'
                    fixture = 'custom/current' if stage == 'v1' else 'expected/after-' + stage
                    shutil.copytree(ROOT/'mechanisms/doc'/fixture, target)
                    renderer = target/'tools/render.py'
                    code = renderer.read_text()
                    original = 'args.output.write_text(result, encoding="utf-8")'
                    self.assertIn(original, code)
                    renderer.write_text(code.replace(original,
                        f'args.output.write_text({expression}, encoding="utf-8")'))
                    result = CHECKS.check_doc(target, CHECKS.read_json(ROOT/f'verifier/expectations/doc-{stage}.json'))
                    self.assertEqual(result['scope'], 'offline-cli-exported-content')
                    self.assertEqual(result['result'], 'PASS')

    def test_api_independent_expectation_rejects_reset_or_unused_timeout_and_regression(self):
        for mutation in ('timeout','unused','health'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                target = Path(temp)/'target'
                shutil.copytree(ROOT/'mechanisms/api/expected/after-v3',target)
                if mutation == 'timeout':
                    (target/'config.json').write_text('{"timeout":30}')
                elif mutation == 'unused':
                    path=target/'tools/client.py'; path.write_text(path.read_text().replace('timeout=config["timeout"]','timeout=30'))
                else:
                    path=target/'tools/service.py'; path.write_text(path.read_text().replace('"status": "ok"','"status": "broken"'))
                with self.assertRaises(AssertionError):
                    CHECKS.check_api(target, CHECKS.read_json(ROOT/'verifier/expectations/api-v3.json'))

    def test_doc_rejects_swapped_source_references(self):
        for stage in ('v2', 'v3', 'incremental'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp:
                target = Path(temp)/'target'
                shutil.copytree(ROOT/f'mechanisms/doc/expected/after-{stage}', target)
                renderer = target/'tools/render.py'
                code = renderer.read_text()
                self.assertIn('source = known[ident]', code)
                renderer.write_text(code.replace('source = known[ident]', 'source = known["s2" if ident == "s1" else "s1"]'))
                with self.assertRaisesRegex(AssertionError, 'source reference mapping changed'):
                    CHECKS.check_doc(target, CHECKS.read_json(ROOT/f'verifier/expectations/doc-{stage}.json'))

    def test_live_api_checks_http_contract_and_closes_services(self):
        for version in (2, 3):
            for mutation in (None, 'all_200', 'health_status', 'unknown_body'):
                with self.subTest(version=version, mutation=mutation), tempfile.TemporaryDirectory() as temp:
                    target = Path(temp)/'target'
                    shutil.copytree(ROOT/f'mechanisms/api/expected/after-v{version}', target)
                    if mutation:
                        path = target/'tools/service.py'
                        code = path.read_text()
                        if mutation == 'all_200':
                            original, replacement = 'self.send_response(status)', 'self.send_response(200)'
                            failure = 'HTTP status changed: /unknown'
                        elif mutation == 'health_status':
                            original, replacement = 'self.send_response(status)', 'self.send_response(201 if self.path == "/health" else status)'
                            failure = 'HTTP status changed: /health'
                        else:
                            original = 'body = json.dumps(value).encode("utf-8")'
                            replacement = 'body = json.dumps({"error": "wrong"} if self.path == "/unknown" else value).encode("utf-8")'
                            failure = 'HTTP body changed: /unknown'
                        self.assertIn(original, code)
                        path.write_text(code.replace(original, replacement))
                    expected = CHECKS.read_json(ROOT/f'verifier/expectations/api-v{version}.json')
                    self.assertEqual(CHECKS.check_api(target, expected)['result'], 'PASS')
                    service = CHECKS.load_module(target/'tools/service.py')
                    client = CHECKS.load_module(target/'tools/client.py')
                    servers, workers = [], []
                    make_server = service.make_server

                    def tracked_server(items):
                        server = make_server(items)
                        servers.append(server)
                        return server

                    def tracked_thread(*args, **kwargs):
                        worker = threading.Thread(*args, **kwargs)
                        workers.append(worker)
                        return worker

                    with patch.object(CHECKS, 'load_module', side_effect=[service, client]), \
                            patch.object(service, 'make_server', side_effect=tracked_server), \
                            patch.object(CHECKS, 'threading') as owned_threads:
                        owned_threads.Thread.side_effect = tracked_thread
                        if mutation:
                            with self.assertRaisesRegex(AssertionError, failure):
                                CHECKS.check_api(target, expected, live=True)
                        else:
                            self.assertEqual(CHECKS.check_api(target, expected, live=True)['result'], 'PASS')
                    self.assertEqual(len(servers), 1)
                    self.assertEqual(len(workers), 1)
                    self.assertEqual(servers[0].socket.fileno(), -1)
                    self.assertFalse(workers[0].is_alive())

    def test_no_accepted_A_is_fabricated(self):
        for kind in ('doc','api'):
            composition=CHECKS.read_json(ROOT/f'mechanisms/{kind}/harness-composition.json')
            self.assertIsNone(composition['accepted_A'])
            for plan in (ROOT/f'mechanisms/{kind}/scenarios').glob('*/upgrade-plan.json'):
                self.assertIsNone(CHECKS.read_json(plan)['accepted_A'])
        incremental=CHECKS.read_json(ROOT/'mechanisms/doc/scenarios/incremental/inputs.json')
        self.assertIsNone(incremental['files'][0]['G'])


if __name__ == '__main__':
    unittest.main()
