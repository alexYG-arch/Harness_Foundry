"""State, CAS, idempotency, freeze, and authoring-stop tests."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from types import ModuleType
import unittest

from harness_foundry_factory.models import (
    ChatRequest,
    IdempotencyConflictError,
    InvalidTransitionError,
    RequestValidationError,
    StateConflictError,
)
from harness_foundry_factory.service import FactoryService
from harness_foundry_factory.store import SQLiteEventStore


class FactoryStateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.spec_root = self.root / "spec"
        self.spec_root.mkdir()
        (self.spec_root / "PACKAGE_MANIFEST.json").write_text(
            json.dumps(
                {
                    "package_id": "HARNESS_FOUNDRY_V2_8_START_PACKAGE",
                    "version": "2.8.0",
                }
            ),
            encoding="utf-8",
        )
        (self.spec_root / "PACKAGE_VALIDATION_REPORT.json").write_text(
            json.dumps(
                {
                    "status": "CONTROLLED_PROGRESSION_AUTHORING_PACKAGE_VALIDATED_NOT_RUNTIME",
                    "checks": [{"check_id": "TEST", "status": "PASS"}],
                }
            ),
            encoding="utf-8",
        )
        self.store = SQLiteEventStore(self.root / "factory.sqlite3")
        self.service = FactoryService(
            self.store,
            spec_root=self.spec_root,
            runs_root=self.root / "runs",
            clock=self._clock,
            allow_unlocked_spec_for_tests=True,
        )
        self.clock_tick = 0

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _clock(self) -> str:
        self.clock_tick += 1
        return f"2026-07-10T00:00:{self.clock_tick:02d}Z"

    @staticmethod
    def _actor(number: int) -> dict[str, str]:
        return {
            "type": "HUMAN_VIA_CODEX_CHAT",
            "chat_thread_id": "THREAD-1",
            "turn_id": f"TURN-{number}",
        }

    def _request(
        self,
        intent: str,
        *,
        number: int,
        program_id: str | None = "PROGRAM-1",
        expected_state_hash: str | None = None,
        payload: dict | None = None,
    ) -> dict:
        return {
            "request_id": f"REQUEST-{number}",
            "idempotency_key": f"IDEMPOTENCY-{number}",
            "program_id": program_id,
            "expected_state_hash": expected_state_hash,
            "actor": self._actor(number),
            "intent": intent,
            "payload": payload or {},
        }

    def _canonical_ir(self) -> dict:
        return {
            "target": {
                "id": "TARGET-1",
                "name": "Example Harness",
                "type": "HARNESS",
                "profile": "FULL",
                "output_root": str(self.root / "target-output"),
                "mission": "Build a bounded example Harness.",
                "scope": ["authoring", "runtime"],
                "non_goals": ["real target installation"],
                "primary_runtime": "python-console-script",
            },
            "atoms": [
                {"atom_id": "REQ-001", "statement": "Preserve the complete input."}
            ],
            "acceptance_cases": [
                {
                    "case_id": "POS-001",
                    "atom_ids": ["REQ-001"],
                    "description": "Candidate is produced with complete traceability.",
                    "expected": "candidate produced",
                }
            ],
            "negative_cases": [
                {
                    "case_id": "NEG-001",
                    "atom_ids": ["REQ-001"],
                    "description": "Automatic Workpack start is rejected.",
                    "expected": "auto start rejected",
                }
            ],
        }

    def _create_and_complete_requirements(self) -> tuple[dict, dict]:
        created = self.service.handle_chat_turn(
            self._request("CREATE", number=1, payload={})
        )
        updated = self.service.handle_chat_turn(
            self._request(
                "UPDATE_REQUIREMENTS",
                number=2,
                expected_state_hash=created["new_state_hash"],
                payload={"requirement_ir": self._canonical_ir()},
            )
        )
        return created, updated

    def _freeze(self) -> tuple[dict, dict, dict, dict]:
        created, updated = self._create_and_complete_requirements()
        readback = self.service.handle_chat_turn(
            self._request(
                "PREPARE_READBACK",
                number=3,
                expected_state_hash=updated["new_state_hash"],
            )
        )
        requested = self.service.handle_chat_turn(
            self._request(
                "REQUEST_FREEZE",
                number=4,
                expected_state_hash=readback["new_state_hash"],
            )
        )
        challenge = requested["approval_challenge"]
        confirmed = self.service.handle_chat_turn(
            self._request(
                "CONFIRM_FREEZE",
                number=5,
                expected_state_hash=requested["new_state_hash"],
                payload={
                    "challenge_id": challenge["challenge_id"],
                    "requirement_ir_sha256": challenge["requirement_ir_sha256"],
                    "decision": "APPROVE",
                    "confirmation_text": challenge["confirmation_token"],
                },
            )
        )
        return created, readback, requested, confirmed

    def test_request_requires_complete_actor(self) -> None:
        value = self._request("CREATE", number=1)
        value["actor"] = {"type": "HUMAN_VIA_CODEX_CHAT"}
        with self.assertRaises(RequestValidationError):
            ChatRequest.from_dict(value)

    def test_intake_clarify_readback_and_human_freeze(self) -> None:
        _, readback, requested, confirmed = self._freeze()
        self.assertEqual(readback["factory_state"], "REQUIREMENTS_READBACK_READY")
        self.assertEqual(requested["factory_state"], "WAITING_REQUIREMENTS_FREEZE")
        self.assertEqual(confirmed["factory_state"], "REQUIREMENTS_FROZEN")
        record = self.store.get_program("PROGRAM-1")
        self.assertEqual(record.snapshot["freeze"]["status"], "FROZEN")
        self.assertEqual(
            record.snapshot["authoring_boundary"]["execution_mode"], "AUTHORING_ONLY"
        )
        self.assertFalse(record.snapshot["authoring_boundary"]["execution_started"])

    def test_stale_state_hash_is_rejected(self) -> None:
        created, updated = self._create_and_complete_requirements()
        with self.assertRaises(StateConflictError):
            self.service.handle_chat_turn(
                self._request(
                    "PREPARE_READBACK",
                    number=3,
                    expected_state_hash=created["new_state_hash"],
                )
            )
        self.assertEqual(self.store.get_program("PROGRAM-1").revision, 2)
        self.assertNotEqual(created["new_state_hash"], updated["new_state_hash"])

    def test_idempotent_replay_returns_same_response_once(self) -> None:
        request = self._request("CREATE", number=1)
        first = self.service.handle_chat_turn(request)
        second = self.service.handle_chat_turn(request)
        self.assertEqual(first, second)
        self.assertEqual(len(self.store.list_events("PROGRAM-1")), 1)

    def test_idempotency_key_cannot_be_reused_with_different_content(self) -> None:
        request = self._request("CREATE", number=1)
        self.service.handle_chat_turn(request)
        changed = dict(request)
        changed["payload"] = {"description": "different"}
        with self.assertRaises(IdempotencyConflictError):
            self.service.handle_chat_turn(changed)

    def test_frozen_requirements_require_explicit_reopen(self) -> None:
        _, _, _, frozen = self._freeze()
        with self.assertRaises(InvalidTransitionError):
            self.service.handle_chat_turn(
                self._request(
                    "UPDATE_REQUIREMENTS",
                    number=6,
                    expected_state_hash=frozen["new_state_hash"],
                    payload={"mission": "silently changed"},
                )
            )
        reopened = self.service.handle_chat_turn(
            self._request(
                "REOPEN",
                number=7,
                expected_state_hash=frozen["new_state_hash"],
                payload={"reason": "User changed mission scope."},
            )
        )
        self.assertEqual(reopened["factory_state"], "CLARIFYING")
        record = self.store.get_program("PROGRAM-1")
        self.assertEqual(record.snapshot["freeze"]["status"], "INVALIDATED_BY_REOPEN")
        self.assertEqual(record.snapshot["candidate"]["status"], "INVALIDATED_BY_REOPEN")

    def test_verify_run_checks_event_and_state_hash_chain(self) -> None:
        self._freeze()
        report = self.service.verify_run("PROGRAM-1")
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["event_count"], 5)
        self.assertEqual(report["errors"], [])

    def test_generate_stops_at_authoring_candidate(self) -> None:
        _, _, _, frozen = self._freeze()
        compiler_module = ModuleType("harness_foundry_factory.compiler")
        validator_module = ModuleType("harness_foundry_factory.validator")

        def compile_candidate(
            requirement_ir: dict,
            spec_root: Path,
            staging_root: Path,
            target_root: Path,
            created_at: str,
            spec_lock: dict,
        ) -> dict:
            target_root.mkdir(parents=True)
            (target_root / "START_CONTEXT.json").write_text(
                json.dumps(
                    {
                        "current_state": "START_PACKAGE_CANDIDATE_READY_FOR_HUMAN_REVIEW",
                        "execution_mode": "AUTHORING_ONLY",
                        "execution_started": False,
                        "install_started": False,
                        "certification_started": False,
                        "auto_start_generated_workpacks": False,
                        "program_driver_started": False,
                    }
                ),
                encoding="utf-8",
            )
            return {"candidate_path": str(target_root), "content_sha256": "abc"}

        def validate_candidate(root: Path, spec_lock: dict | None = None) -> dict:
            return {"status": "PASS", "candidate_root": str(root)}

        compiler_module.compile_candidate = compile_candidate  # type: ignore[attr-defined]
        validator_module.validate_candidate = validate_candidate  # type: ignore[attr-defined]
        previous_compiler = sys.modules.get("harness_foundry_factory.compiler")
        previous_validator = sys.modules.get("harness_foundry_factory.validator")
        sys.modules["harness_foundry_factory.compiler"] = compiler_module
        sys.modules["harness_foundry_factory.validator"] = validator_module
        try:
            generated = self.service.handle_chat_turn(
                self._request(
                    "GENERATE",
                    number=6,
                    expected_state_hash=frozen["new_state_hash"],
                )
            )
        finally:
            if previous_compiler is None:
                sys.modules.pop("harness_foundry_factory.compiler", None)
            else:
                sys.modules["harness_foundry_factory.compiler"] = previous_compiler
            if previous_validator is None:
                sys.modules.pop("harness_foundry_factory.validator", None)
            else:
                sys.modules["harness_foundry_factory.validator"] = previous_validator

        self.assertEqual(generated["factory_state"], "CANDIDATE_READY_FOR_HUMAN_REVIEW")
        self.assertEqual(generated["hard_stop"], "START_PACKAGE_HUMAN_REVIEW")
        candidate = self.store.get_program("PROGRAM-1").snapshot["candidate"]
        self.assertFalse(candidate["execution_started"])
        self.assertFalse(candidate["auto_start_generated_workpacks"])
        self.assertEqual(candidate["human_approval_status"], "PENDING")


if __name__ == "__main__":
    unittest.main()
