"""Scoped regressions for executable paths and historical JSONL diagnostics."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import venv

from tests.python_fixture import python_fixture_header
from harness_foundry_factory.validator import _check_syntax


class FixturePathTests(unittest.TestCase):
    def test_quoted_interpreter_preserves_venv_arguments_and_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            environment = root / "python env 汉' $literal"
            venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
            python = environment / "bin/python"
            script = root / "receiver with spaces"
            script.write_text(python_fixture_header(python) +
                'import json, sys\n'
                'print(json.dumps({"python":sys.executable,"prefix":sys.prefix,"args":sys.argv[1:]}))\n'
                'raise SystemExit(7)\n')
            script.chmod(0o700)
            args = ['one two', '汉字', '$not-expanded', "a'b"]
            for command in ([str(script)], [str(python), str(script)]):
                with self.subTest(command=command):
                    result = subprocess.run([*command, *args], capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 7, result.stderr)
                    observed = json.loads(result.stdout)
                    self.assertEqual(observed['python'], str(python))
                    self.assertEqual(Path(observed['prefix']), environment)
                    self.assertEqual(observed['args'], args)


class JsonlDiagnosticTests(unittest.TestCase):
    def test_first_unreadable_file_keeps_io_diagnostic(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'first.jsonl').write_text('{}\n')
            with patch.object(Path, 'read_text', side_effect=PermissionError('not readable')):
                findings = _check_syntax(root)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]['code'], 'JSONL_INVALID')
            self.assertIn('first.jsonl:0: not readable', findings[0]['message'])

    def test_unreadable_later_file_does_not_reuse_previous_line(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'a.jsonl').write_text('{}\n{}\n{}\n')
            (root / 'b.jsonl').write_bytes(b'\xff')
            findings = _check_syntax(root)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]['code'], 'JSONL_INVALID')
            self.assertIn('b.jsonl:0:', findings[0]['message'])

    def test_malformed_json_preserves_line_and_valid_jsonl_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'record.jsonl'
            path.write_text('{}\nnot-json\n')
            findings = _check_syntax(root)
            self.assertEqual(findings[0]['code'], 'JSONL_INVALID')
            self.assertIn('record.jsonl:2:', findings[0]['message'])
            path.write_text('{}\n\n{"ok":true}\n')
            self.assertEqual(_check_syntax(root), [])
