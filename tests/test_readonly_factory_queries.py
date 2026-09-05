from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from harness_foundry_factory.service import FactoryService
from harness_foundry_factory.cli import main


class ReadOnlyFactoryQueryTests(TestCase):
    def test_status_and_readback_do_not_export(self):
        record = SimpleNamespace(
            snapshot={"requirement_ir": {}, "freeze": {}},
            factory_state="CANDIDATE_READY_FOR_HUMAN_REVIEW",
            as_status=lambda: {"revision": 150},
        )
        service = FactoryService(Mock(get_program=Mock(return_value=record)),
                                 spec_root=Path("."), runs_root=Path("runs"))
        with patch.object(service, "_export_program_views") as writer, \
                patch.object(service, "_requirement_gaps", return_value=[]):
            self.assertEqual(service.status("fixture")["revision"], 150)
            self.assertEqual(service.readback("fixture")["revision"], 150)
            writer.assert_not_called()

    def test_cli_queries_open_readonly_store_without_creating_missing_program(self):
        for command in ("status", "readback"):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                missing = Path(directory) / "never-created"
                with redirect_stdout(StringIO()):
                    code = main([command, "--program-id", "PROGRAM-MISSING", "--runs-root", str(missing), "--json"])
                self.assertNotEqual(code, 0)
                self.assertFalse(missing.exists())
