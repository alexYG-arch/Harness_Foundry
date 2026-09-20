"""Real Chat/CLI authoring path, persistence recovery, and terminal-stop E2E test."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from harness_foundry_factory.constants import default_spec_root
from harness_foundry_factory.models import ProgramNotFoundError
from harness_foundry_factory.service import FactoryService
from harness_foundry_factory.store import SQLiteEventStore
from tests.build_review_fixture import reviewed_document


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "harness_requirement_ir.json"


class ChatCliEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.runs_root = self.root / "runs"
        self.candidate_root = self.root / "reference-start-package"
        self.program_id = "PROGRAM-CHAT-CLI-E2E"
        self.spec_root = default_spec_root().resolve()
        self.request_number = 0

        requirement_ir = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.requirement_ir = deepcopy(requirement_ir)
        self.requirement_ir["program_id"] = self.program_id
        self.requirement_ir["target"]["output_root"] = str(self.candidate_root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _request(
        self,
        intent: str,
        *,
        expected_state_hash: str | None,
        payload: dict | None = None,
    ) -> dict:
        self.request_number += 1
        if intent == "CREATE":
            payload = {**(payload or {}), "build_document_review": reviewed_document(self.root)}
        return {
            "request_id": f"REQUEST-E2E-{self.request_number:02d}",
            "idempotency_key": f"IDEMPOTENCY-E2E-{self.request_number:02d}",
            "program_id": self.program_id,
            "expected_state_hash": expected_state_hash,
            "actor": {
                "type": "HUMAN_VIA_CODEX_CHAT",
                "chat_thread_id": "THREAD-E2E-ORIGINAL",
                "turn_id": f"TURN-{self.request_number:02d}",
            },
            "intent": intent,
            "payload": payload or {},
        }

    def _run_cli(self, *arguments: str) -> dict:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "harness_foundry_factory.cli",
                *arguments,
                "--spec-root",
                str(self.spec_root),
                "--runs-root",
                str(self.runs_root),
                "--json",
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"CLI failed:\nstdout={completed.stdout}\nstderr={completed.stderr}",
        )
        stdout_lines = completed.stdout.splitlines()
        self.assertEqual(stdout_lines, [completed.stdout.strip()])
        result = json.loads(completed.stdout)
        self.assertIsInstance(result, dict)
        return result

    def _chat_turn(self, request: dict) -> dict:
        request_path = self.root / f"{request['request_id']}.json"
        request_path.write_text(
            json.dumps(request, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        return self._run_cli("chat-turn", "--request", str(request_path))

    def test_chat_cli_builds_valid_candidate_and_recovers_by_program_id(self) -> None:
        created = self._chat_turn(
            self._request(
                "CREATE",
                expected_state_hash=None,
                payload={"requirement_ir": self.requirement_ir},
            )
        )
        self.assertEqual(created["factory_state"], "CLARIFYING")
        self.assertEqual(created["questions"], [])

        readback = self._chat_turn(
            self._request(
                "PREPARE_READBACK",
                expected_state_hash=created["new_state_hash"],
            )
        )
        self.assertEqual(
            readback["factory_state"], "REQUIREMENTS_READBACK_READY"
        )
        self.assertEqual(readback["requirement_ir"]["program_id"], self.program_id)

        freeze_request = self._chat_turn(
            self._request(
                "REQUEST_FREEZE",
                expected_state_hash=readback["new_state_hash"],
            )
        )
        self.assertEqual(
            freeze_request["factory_state"], "WAITING_REQUIREMENTS_FREEZE"
        )
        challenge = freeze_request["approval_challenge"]

        frozen = self._chat_turn(
            self._request(
                "CONFIRM_FREEZE",
                expected_state_hash=freeze_request["new_state_hash"],
                payload={
                    "challenge_id": challenge["challenge_id"],
                    "requirement_ir_sha256": challenge["requirement_ir_sha256"],
                    "decision": "APPROVE",
                    "confirmation_text": challenge["confirmation_token"],
                },
            )
        )
        self.assertEqual(frozen["factory_state"], "REQUIREMENTS_FROZEN")

        generated = self._chat_turn(
            self._request(
                "GENERATE",
                expected_state_hash=frozen["new_state_hash"],
            )
        )
        self.assertEqual(
            generated["factory_state"], "CANDIDATE_READY_FOR_HUMAN_REVIEW"
        )
        self.assertEqual(
            generated["candidate"]["status"],
            "START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW",
        )
        self.assertEqual(generated["hard_stop"], "START_PACKAGE_HUMAN_REVIEW")
        self.assertEqual(
            Path(generated["candidate"]["candidate_path"]).resolve(),
            self.candidate_root.resolve(),
        )
        self.assertTrue(self.candidate_root.is_dir())

        candidate_validation = self._run_cli(
            "validate-candidate", "--program-id", self.program_id
        )
        self.assertEqual(candidate_validation["status"], "PASS")
        run_verification = self._run_cli("verify-run", "--program-id", self.program_id)
        self.assertEqual(run_verification["status"], "PASS")
        self.assertEqual(run_verification["event_count"], 5)

        database_path = self.runs_root / self.program_id / "factory.sqlite3"
        self.assertTrue(database_path.is_file())
        run_root = database_path.parent
        for relative in (
            "sources",
            "requirement_ir",
            "decisions",
            "staging",
            "validation",
            "readback",
            "FACTORY_STATE.json",
            "sources/SOURCE_REGISTRY.json",
            "requirement_ir/CURRENT_REQUIREMENT_IR.json",
            "decisions/DECISIONS.json",
            "readback/READBACK.json",
            "readback/EVENTS.jsonl",
        ):
            self.assertTrue((run_root / relative).exists(), msg=relative)
        exported_events = [
            json.loads(line)
            for line in (run_root / "readback/EVENTS.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        self.assertEqual(len(exported_events), 5)
        self.assertEqual(exported_events[-1]["new_state_hash"], generated["new_state_hash"])

        second_program_id = "PROGRAM-CHAT-CLI-E2E-SECOND"
        second_ir = deepcopy(self.requirement_ir)
        second_ir["program_id"] = second_program_id
        second_request = self._request(
            "CREATE",
            expected_state_hash=None,
            payload={"requirement_ir": second_ir},
        )
        second_request["program_id"] = second_program_id
        second_created = self._chat_turn(second_request)
        self.assertEqual(second_created["program_id"], second_program_id)
        second_database = self.runs_root / second_program_id / "factory.sqlite3"
        self.assertTrue(second_database.is_file())
        self.assertNotEqual(database_path, second_database)
        self.assertFalse((self.runs_root / "factory.sqlite3").exists())
        with self.assertRaises(ProgramNotFoundError):
            SQLiteEventStore(second_database).get_program(self.program_id)
        with self.assertRaises(ProgramNotFoundError):
            SQLiteEventStore(database_path).get_program(second_program_id)

        resumed_store = SQLiteEventStore(database_path)
        resumed_service = FactoryService(
            resumed_store,
            spec_root=self.spec_root,
            runs_root=self.runs_root,
        )
        resumed_status = resumed_service.status(self.program_id)
        self.assertEqual(resumed_status["revision"], 5)
        self.assertEqual(
            resumed_status["factory_state"], "CANDIDATE_READY_FOR_HUMAN_REVIEW"
        )
        self.assertEqual(
            resumed_status["candidate_status"],
            "START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW",
        )
        resumed_readback = resumed_service.readback(self.program_id)
        self.assertEqual(resumed_readback["freeze"]["status"], "FROZEN")
        self.assertEqual(
            resumed_readback["candidate"]["candidate_path"],
            str(self.candidate_root.resolve()),
        )
        self.assertEqual(resumed_service.verify_run(self.program_id)["status"], "PASS")
        self.assertEqual(
            resumed_service.validate_program_candidate(self.program_id)["status"],
            "PASS",
        )


if __name__ == "__main__":
    unittest.main()
