"""Required Agent, ambiguous Harness, and conflicting Hybrid fixtures."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from harness_foundry_factory.compiler import compile_candidate
from harness_foundry_factory.service import FactoryService
from harness_foundry_factory.store import SQLiteEventStore
from harness_foundry_factory.validator import validate_candidate
from tests.build_review_fixture import reviewed_document


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT.parent / "Harness_Foundry_v2_8_Start_Package"
FIXTURES = ROOT / "tests/fixtures"


class RequiredFixtureTests(unittest.TestCase):
    def _service(self, root: Path) -> FactoryService:
        self.root = root
        return FactoryService(
            SQLiteEventStore(root / "factory.sqlite3"),
            spec_root=SPEC,
            runs_root=root / "runs",
            clock=lambda: "2026-07-10T00:00:00Z",
        )

    def _request(self, program_id: str, payload: dict) -> dict:
        return {
            "request_id": "REQ-1", "idempotency_key": "IDEM-1",
            "program_id": program_id, "expected_state_hash": None,
            "actor": {"type": "HUMAN_VIA_CODEX_CHAT", "chat_thread_id": "FIXTURE", "turn_id": "TURN-1"},
            "intent": "CREATE", "payload": {**payload, "build_document_review": reviewed_document(self.root)},
        }

    def test_ambiguous_harness_returns_at_most_three_questions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            payload = json.loads((FIXTURES / "ambiguous_harness_intake.json").read_text())
            response = self._service(Path(temporary)).handle_chat_turn(
                self._request("PROGRAM-AMBIGUOUS-HARNESS", {"requirement_ir": payload})
            )
            self.assertEqual(response["status"], "WAITING_USER")
            self.assertGreater(response["question_count"], 3)
            self.assertLessEqual(len(response["questions"]), 3)

    def test_complete_agent_compiles_and_validates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ir = json.loads((FIXTURES / "agent_requirement_ir.json").read_text())
            candidate = Path(temporary) / "agent-candidate"
            ir["target"]["output_root"] = str(candidate)
            compile_candidate(ir, SPEC, Path(temporary) / "staging", candidate, "2026-07-10T00:00:00Z")
            self.assertEqual(validate_candidate(candidate)["status"], "PASS")
            runtime = json.loads((candidate / "constitution/RUNTIME_OWNERSHIP.json").read_text())
            self.assertEqual(runtime["target_type"], "AGENT")
            self.assertEqual(runtime["required_executor"]["name"], "Codex")

    def test_hybrid_source_conflict_blocks_readback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ir = json.loads((FIXTURES / "hybrid_conflict_requirement_ir.json").read_text())
            response = self._service(Path(temporary)).handle_chat_turn(
                self._request("PROGRAM-CONFLICT-HYBRID", {"requirement_ir": ir})
            )
            self.assertTrue(any(item["origin"] == "SOURCE_CONFLICT" for item in response["questions"]))


if __name__ == "__main__":
    unittest.main()
