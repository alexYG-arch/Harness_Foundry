"""Hardening tests for source locks, human gates, reopen, and run integrity."""

from __future__ import annotations

from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import ModuleType
import unittest

from harness_foundry_factory.models import (
    ChatRequest,
    InvalidTransitionError,
    RequestValidationError,
)
from harness_foundry_factory.service import FactoryService
from harness_foundry_factory.store import SQLiteEventStore


class FactoryHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
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
        self.runs_root = self.root / "runs"
        self.database = self.runs_root / "PROGRAM-HARDENING" / "factory.sqlite3"
        self.store = SQLiteEventStore(self.database)
        self.clock_tick = 0
        self.request_number = 0
        self.service = FactoryService(
            self.store,
            spec_root=self.spec_root,
            runs_root=self.runs_root,
            clock=self._clock,
            allow_unlocked_spec_for_tests=True,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _clock(self) -> str:
        self.clock_tick += 1
        return f"2026-07-10T01:00:{self.clock_tick:02d}Z"

    def _request(
        self,
        intent: str,
        *,
        expected_state_hash: str | None = None,
        payload: dict | None = None,
        program_id: str = "PROGRAM-HARDENING",
    ) -> dict:
        self.request_number += 1
        return {
            "request_id": f"REQUEST-HARDENING-{self.request_number:02d}",
            "idempotency_key": f"IDEMPOTENCY-HARDENING-{self.request_number:02d}",
            "program_id": program_id,
            "expected_state_hash": expected_state_hash,
            "actor": {
                "type": "HUMAN_VIA_CODEX_CHAT",
                "chat_thread_id": "THREAD-HARDENING",
                "turn_id": f"TURN-{self.request_number:02d}",
            },
            "intent": intent,
            "payload": payload or {},
        }

    def _complete_ir(self) -> dict:
        return {
            "target": {
                "id": "TARGET-HARDENING",
                "name": "Hardening Harness",
                "type": "HARNESS",
                "profile": "FULL",
                "output_root": str(self.root / "candidate"),
                "mission": "Build a bounded Harness Start Package.",
                "scope": ["authoring", "three-project plan"],
                "non_goals": ["execute Workpacks"],
                "primary_runtime": "Codex",
            },
            "atoms": [
                {
                    "atom_id": "ATOM-001",
                    "statement": "Keep authoring separate from execution.",
                }
            ],
            "acceptance_cases": [
                {
                    "case_id": "AC-001",
                    "atom_ids": ["ATOM-001"],
                    "description": "The candidate is review-ready.",
                    "expected": "candidate is review-ready",
                }
            ],
            "negative_cases": [
                {
                    "case_id": "NEG-001",
                    "atom_ids": ["ATOM-001"],
                    "description": "Authoring cannot grant execution.",
                    "expected": "execution remains denied",
                }
            ],
            "assumptions": [],
            "open_questions": [],
            "decisions": [],
        }

    def _create(self, ir: dict | None = None) -> dict:
        return self.service.handle_chat_turn(
            self._request(
                "CREATE",
                payload={"requirement_ir": ir or self._complete_ir()},
            )
        )

    def _freeze_challenge(self, ir: dict | None = None) -> tuple[dict, dict]:
        created = self._create(ir)
        readback = self.service.handle_chat_turn(
            self._request(
                "PREPARE_READBACK",
                expected_state_hash=created["new_state_hash"],
            )
        )
        requested = self.service.handle_chat_turn(
            self._request(
                "REQUEST_FREEZE",
                expected_state_hash=readback["new_state_hash"],
            )
        )
        return requested, requested["approval_challenge"]

    def _confirm(self, requested: dict, challenge: dict) -> dict:
        return self.service.handle_chat_turn(
            self._request(
                "CONFIRM_FREEZE",
                expected_state_hash=requested["new_state_hash"],
                payload={
                    "challenge_id": challenge["challenge_id"],
                    "requirement_ir_sha256": challenge["requirement_ir_sha256"],
                    "decision": "APPROVE",
                    "confirmation_text": challenge["confirmation_token"],
                },
            )
        )

    def test_program_id_path_traversal_is_rejected_before_store_selection(self) -> None:
        base = self._request("CREATE", payload={})
        for program_id in ("../ESCAPE", "/tmp/ESCAPE", "nested/ESCAPE", "A..B"):
            with self.subTest(program_id=program_id):
                request = deepcopy(base)
                request["program_id"] = program_id
                with self.assertRaisesRegex(
                    RequestValidationError, "path-safe identifier"
                ):
                    ChatRequest.from_dict(request)
        self.assertFalse((self.root / "ESCAPE").exists())

    def test_local_source_changed_after_challenge_blocks_freeze(self) -> None:
        source = self.root / "requirements.md"
        source.write_text("locked requirement\n", encoding="utf-8")
        ir = self._complete_ir()
        ir["sources"] = [
            {
                "source_id": "SRC-LOCAL-001",
                "path_or_uri": str(source),
                "authority_level": "HUMAN_PROVIDED",
            }
        ]
        requested, challenge = self._freeze_challenge(ir)

        source.write_text("changed after challenge\n", encoding="utf-8")
        blocked = self._confirm(requested, challenge)

        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertEqual(blocked["factory_state"], "BLOCKED_SOURCE_CONFLICT")
        self.assertIn(
            "HF28_SOURCE_CHANGED", {item["code"] for item in blocked["blockers"]}
        )
        record = self.store.get_program("PROGRAM-HARDENING")
        self.assertEqual(record.factory_state, "BLOCKED_SOURCE_CONFLICT")
        self.assertEqual(self.store.list_events("PROGRAM-HARDENING")[-1]["event_type"], "SOURCE_CONFLICT_DETECTED")

    def test_domain_question_and_decision_survive_block_and_resolution(self) -> None:
        ir = self._complete_ir()
        ir["open_questions"] = [
            {
                "question_id": "DOMAIN-SECURITY-MODE",
                "prompt": "Which security mode is authoritative?",
                "field": "requirement_ir.security_mode",
                "blocking": True,
                "status": "OPEN",
                "origin": "USER_REQUIREMENT",
            }
        ]
        ir["decisions"] = [
            {
                "decision_id": "DEC-DOMAIN-001",
                "decision": "The user owns the security-mode decision.",
                "status": "CONFIRMED",
            }
        ]
        created = self._create(ir)
        self.assertEqual(
            [item["question_id"] for item in created["questions"]],
            ["DOMAIN-SECURITY-MODE"],
        )

        blocked = self.service.handle_chat_turn(
            self._request(
                "PREPARE_READBACK",
                expected_state_hash=created["new_state_hash"],
            )
        )
        self.assertEqual(blocked["factory_state"], "BLOCKED_REQUIREMENT_GAP")
        blocked_readback = self.service.readback("PROGRAM-HARDENING")
        self.assertIn(
            "DEC-DOMAIN-001",
            {
                item.get("decision_id")
                for item in blocked_readback["requirement_ir"]["decisions"]
            },
        )
        self.assertIn(
            "DOMAIN-SECURITY-MODE",
            {
                item.get("question_id")
                for item in blocked_readback["requirement_ir"]["open_questions"]
            },
        )

        resolved_question = deepcopy(ir["open_questions"][0])
        resolved_question["status"] = "RESOLVED"
        updated = self.service.handle_chat_turn(
            self._request(
                "UPDATE_REQUIREMENTS",
                expected_state_hash=blocked["new_state_hash"],
                payload={
                    "requirement_ir": {"open_questions": [resolved_question]}
                },
            )
        )
        ready = self.service.handle_chat_turn(
            self._request(
                "PREPARE_READBACK",
                expected_state_hash=updated["new_state_hash"],
            )
        )
        self.assertEqual(ready["factory_state"], "REQUIREMENTS_READBACK_READY")
        final_readback = self.service.readback("PROGRAM-HARDENING")
        questions = {
            item.get("question_id"): item
            for item in final_readback["requirement_ir"]["open_questions"]
        }
        self.assertEqual(questions["DOMAIN-SECURITY-MODE"]["status"], "RESOLVED")
        self.assertIn(
            "DEC-DOMAIN-001",
            {
                item.get("decision_id")
                for item in final_readback["requirement_ir"]["decisions"]
            },
        )

    def test_freeze_confirmation_without_bound_text_is_rejected(self) -> None:
        requested, challenge = self._freeze_challenge()

        with self.assertRaisesRegex(InvalidTransitionError, "confirmation_text"):
            self.service.handle_chat_turn(
                self._request(
                    "CONFIRM_FREEZE",
                    expected_state_hash=requested["new_state_hash"],
                    payload={
                        "challenge_id": challenge["challenge_id"],
                        "requirement_ir_sha256": challenge[
                            "requirement_ir_sha256"
                        ],
                        "decision": "APPROVE",
                    },
                )
            )
        record = self.store.get_program("PROGRAM-HARDENING")
        self.assertEqual(record.factory_state, "WAITING_REQUIREMENTS_FREEZE")
        self.assertEqual(record.revision, 3)

    def test_reopen_generated_candidate_clears_output_and_requires_new_path(self) -> None:
        requested, challenge = self._freeze_challenge()
        frozen = self._confirm(requested, challenge)
        compiler_module = ModuleType("harness_foundry_factory.compiler")
        validator_module = ModuleType("harness_foundry_factory.validator")

        def compile_candidate(
            requirement_ir: dict,
            spec_root: Path,
            staging_root: Path,
            target_root: Path,
            created_at: str,
            spec_lock: dict,
            **_kwargs: object,
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

        def validate_candidate(
            root: Path,
            spec_lock: dict | None = None,
            **_kwargs: object,
        ) -> dict:
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
                    "GENERATE", expected_state_hash=frozen["new_state_hash"]
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

        candidate_path = generated["candidate"]["candidate_path"]
        reopened = self.service.handle_chat_turn(
            self._request(
                "REOPEN",
                expected_state_hash=generated["new_state_hash"],
                payload={"reason": "Author a replacement candidate."},
            )
        )
        self.assertEqual(reopened["factory_state"], "CLARIFYING")
        self.assertIn("REQ-OUTPUT-ROOT", {item["question_id"] for item in reopened["questions"]})
        record = self.store.get_program("PROGRAM-HARDENING")
        target = record.snapshot["requirement_ir"]["target"]
        self.assertIsNone(target["output_root"])
        self.assertEqual(target["previous_output_root"], candidate_path)
        self.assertEqual(
            record.snapshot["candidate"]["invalidated_candidate_path"], candidate_path
        )
        blocked = self.service.handle_chat_turn(
            self._request(
                "PREPARE_READBACK",
                expected_state_hash=reopened["new_state_hash"],
            )
        )
        self.assertEqual(blocked["factory_state"], "BLOCKED_REQUIREMENT_GAP")
        self.assertIn("REQ-OUTPUT-ROOT", {item["question_id"] for item in blocked["questions"]})

    def test_verify_run_detects_factory_state_and_snapshot_read_model_tamper(self) -> None:
        self._create()
        with closing(sqlite3.connect(self.database)) as connection:
            original_state, snapshot_json = connection.execute(
                "SELECT factory_state, snapshot_json FROM programs WHERE program_id = ?",
                ("PROGRAM-HARDENING",),
            ).fetchone()
            connection.execute(
                "UPDATE programs SET factory_state = ? WHERE program_id = ?",
                ("FORGED_STATE", "PROGRAM-HARDENING"),
            )
            connection.commit()
        report = self.store.verify_run("PROGRAM-HARDENING")
        self.assertEqual(report["status"], "FAIL")
        self.assertIn(
            "FACTORY_STATE_READ_MODEL_MISMATCH",
            {item["code"] for item in report["errors"]},
        )

        forged_snapshot = json.loads(snapshot_json)
        forged_snapshot["factory_state"] = "FORGED_SNAPSHOT_STATE"
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                "UPDATE programs SET factory_state = ?, snapshot_json = ? WHERE program_id = ?",
                (
                    original_state,
                    json.dumps(forged_snapshot, separators=(",", ":"), sort_keys=True),
                    "PROGRAM-HARDENING",
                ),
            )
            connection.commit()
        report = self.store.verify_run("PROGRAM-HARDENING")
        codes = {item["code"] for item in report["errors"]}
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("CURRENT_SNAPSHOT_HASH_MISMATCH", codes)
        self.assertIn("FACTORY_STATE_READ_MODEL_MISMATCH", codes)
        self.assertIn("EVENT_SNAPSHOT_READ_MODEL_MISMATCH", codes)


if __name__ == "__main__":
    unittest.main()
