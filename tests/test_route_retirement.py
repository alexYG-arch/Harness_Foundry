"""Public retirement and raw historical reads; never use a real Program."""

from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from harness_foundry_factory.entrypoint import main, RETIRED_COMMANDS
from harness_foundry_factory.legacy_history import read_history
from harness_foundry_factory.build_types import RequestValidationError


ROOT = Path(__file__).resolve().parents[1]


class RouteRetirementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.database = self.root / "history.sqlite3"

    def history(self):
        value = {"requirement_ir": {"target": {"name": "old target"}},
                 "next_allowed_intents": ["GENERATE"], "old_approval": "GRANTED"}
        connection = sqlite3.connect(self.database)
        connection.execute("CREATE TABLE programs (program_id TEXT, revision INTEGER, factory_state TEXT, state_hash TEXT, snapshot_json TEXT)")
        connection.execute("INSERT INTO programs VALUES (?, ?, ?, ?, ?)",
                           ("OLD", 7, "REQUIREMENTS_FROZEN", "recorded-opaque-hash", json.dumps(value)))
        connection.commit()
        connection.close()
        return value

    def test_every_retired_command_stops_before_loading_requests_or_creating_state(self):
        from harness_foundry_factory.cli import main as old_module_main
        for entry in (main, old_module_main):
            for command in sorted(RETIRED_COMMANDS):
                with self.subTest(entry=entry.__module__, command=command), redirect_stdout(StringIO()) as stream, \
                        patch("pathlib.Path.read_text", side_effect=AssertionError("no input read")), \
                        patch("subprocess.Popen", side_effect=AssertionError("no process")):
                    self.assertEqual(entry([command, "--request", str(self.root / "missing.json"), "--json"]), 2)
                result = json.loads(stream.getvalue())
                self.assertEqual(result["error"]["code"], "LEGACY_WORKFLOW_RETIRED")
                self.assertFalse(result["writes_performed"])
                self.assertFalse(result["legacy_fallback_available"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_real_script_and_old_module_cannot_reenter_legacy_creation(self):
        environment = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
        for launcher in ([str(ROOT / "tools/hffactory.py")], ["-m", "harness_foundry_factory.cli"]):
            result = subprocess.run([sys.executable, "-B", *launcher, "chat-turn", "--request",
                                     str(self.root / "missing.json"), "--json"], cwd=self.root,
                                    env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(json.loads(result.stdout)["error"]["code"], "LEGACY_WORKFLOW_RETIRED")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_help_and_version_advertise_the_generic_route_only(self):
        with redirect_stdout(StringIO()) as stream, self.assertRaises(SystemExit) as stopped:
            main(["--help"])
        self.assertEqual(stopped.exception.code, 0)
        self.assertIn("record-build-plan", stream.getvalue())
        self.assertIn("read-history", stream.getvalue())
        self.assertNotIn("chat-turn", stream.getvalue())
        with redirect_stdout(StringIO()) as stream:
            self.assertEqual(main(["version", "--json"]), 0)
        self.assertEqual(json.loads(stream.getvalue())["product_route"], "GENERIC_REVIEWED_BUILD")

    def test_manifest_matches_production_commands_not_historical_api(self):
        from harness_foundry_factory.build_cli import BUILD_COMMANDS
        from harness_foundry_factory.entrypoint import DIAGNOSTIC_COMMANDS
        import importlib
        manifest = json.loads((ROOT / "FACTORY_MANIFEST.json").read_text())
        self.assertEqual(set(manifest["public_cli"]), {"version", *BUILD_COMMANDS})
        self.assertEqual(set(manifest["source_diagnostic_cli"]), DIAGNOSTIC_COMMANDS)
        self.assertFalse(set(manifest["public_cli"]) & RETIRED_COMMANDS)
        self.assertEqual(manifest["legacy_new_build_status"], "RETIRED_NO_FALLBACK")
        for api in manifest["public_python_api"]:
            module, name = api.rsplit(".", 1)
            self.assertTrue(callable(getattr(importlib.import_module(module), name)))

    def test_history_preserves_raw_old_facts_without_reauthorizing_or_rehashing(self):
        expected = self.history()
        before = self.database.read_bytes()
        with patch("hashlib.sha256", side_effect=AssertionError("no new hash")):
            result = read_history(self.database, "OLD")
        self.assertEqual(result["recorded_snapshot"], expected)
        self.assertEqual(result["recorded_state_hash"], "recorded-opaque-hash")
        self.assertEqual(result["next_allowed_intents"], [])
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["migration_performed"])
        self.assertEqual(self.database.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [self.database])

    def test_public_history_needs_no_producer_or_sibling(self):
        expected = self.history()
        program = f'''import sys
sys.path.insert(0, {str(ROOT / "src")!r})
from harness_foundry_factory.entrypoint import main
assert main(["read-history", "--database", {str(self.database)!r}, "--program-id", "OLD", "--json"]) == 0
assert "harness_foundry_factory.service" not in sys.modules
assert "harness_foundry_factory.compiler" not in sys.modules
assert "harness_foundry_factory.store" not in sys.modules
'''
        result = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", program], cwd=self.root,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["recorded_snapshot"], expected)

    def test_missing_invalid_and_unknown_history_never_initializes_a_database(self):
        with self.assertRaises(RequestValidationError):
            read_history(self.database, "OLD")
        self.assertFalse(self.database.exists())
        self.database.write_bytes(b"not a database")
        with self.assertRaises(RequestValidationError):
            read_history(self.database, "OLD")
        self.assertEqual(self.database.read_bytes(), b"not a database")
        self.database.unlink()
        self.history()
        before = self.database.read_bytes()
        with self.assertRaises(RequestValidationError):
            read_history(self.database, "OTHER")
        self.assertEqual(self.database.read_bytes(), before)

    def test_live_wal_is_not_ignored_checkpointed_or_modified(self):
        self.history()
        connection = sqlite3.connect(self.database)
        self.addCleanup(connection.close)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("UPDATE programs SET revision=8")
        connection.commit()
        before = {path.name: path.read_bytes() for path in self.root.iterdir()}
        with self.assertRaisesRegex(RequestValidationError, "live WAL"):
            read_history(self.database, "OLD")
        self.assertEqual({path.name: path.read_bytes() for path in self.root.iterdir()}, before)


if __name__ == "__main__":
    unittest.main()
