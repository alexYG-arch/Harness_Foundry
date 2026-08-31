"""Slice 04 authoring auto-advance public CLI and single-CAS behavior."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from harness_foundry_factory.service import FactoryService
from harness_foundry_factory.models import StateConflictError
from harness_foundry_factory.store import SQLiteEventStore


ROOT = Path(__file__).resolve().parents[1]


class AdvanceAuthoringCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.spec_root = ROOT.parent / "Harness_Foundry_v2_8_Start_Package"
        self.runs_root = self.root / "runs"
        self.program_id = "PROGRAM-SLICE-04"
        self.store = SQLiteEventStore(
            self.runs_root / self.program_id / "factory.sqlite3"
        )
        self.service = FactoryService(
            self.store,
            spec_root=self.spec_root,
            runs_root=self.runs_root,
        )
        self.request_number = 0

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _request(self, intent: str, expected: str | None, payload: dict) -> dict:
        self.request_number += 1
        return {
            "request_id": f"REQ-SLICE-04-{self.request_number}",
            "idempotency_key": f"IDEM-SLICE-04-{self.request_number}",
            "program_id": self.program_id,
            "expected_state_hash": expected,
            "actor": {
                "type": "HUMAN_VIA_CODEX_CHAT",
                "chat_thread_id": "THREAD-SLICE-04",
                "turn_id": f"TURN-SLICE-04-{self.request_number}",
            },
            "intent": intent,
            "payload": payload,
        }

    def _complete_ir(self, *, architecture_epoch: int = 4, control_epoch: int = 4) -> dict:
        return {
            "target": {
                "id": "TARGET-SLICE-04",
                "name": "Slice 04 Harness",
                "type": "HARNESS",
                "profile": "FULL",
                "output_root": str(self.root / "candidate-must-remain-absent"),
                "mission": "Compile authoring state to the next real gate.",
                "scope": ["authoring"],
                "non_goals": ["execution", "installation"],
                "primary_runtime": "python-console-script",
                "architecture_epoch": architecture_epoch,
                "control_plane_epoch": control_epoch,
            },
            "atoms": [
                {
                    "atom_id": "REQ-SLICE-04",
                    "statement": "Advance internal authoring checks automatically.",
                }
            ],
            "acceptance_cases": [
                {
                    "case_id": "POS-SLICE-04",
                    "atom_ids": ["REQ-SLICE-04"],
                    "description": "Authoring reaches Readback in one CAS.",
                    "expected": "READY_FOR_READBACK",
                }
            ],
            "negative_cases": [
                {
                    "case_id": "NEG-SLICE-04",
                    "atom_ids": ["REQ-SLICE-04"],
                    "description": "Mixed epoch input is rejected.",
                    "expected": "MIXED_EPOCH",
                }
            ],
        }

    def _create(self, requirement_ir: dict | None = None) -> dict:
        return self.service.handle_chat_turn(
            self._request(
                "CREATE",
                None,
                {"requirement_ir": requirement_ir or {}},
            )
        )

    def _run_cli(self) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment["PYTHONDWRITEBYTECODE"] = "1"
        return subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "harness_foundry_factory.cli",
                "advance-authoring-until-gate",
                "--program-id",
                self.program_id,
                "--spec-root",
                str(self.spec_root),
                "--runs-root",
                str(self.runs_root),
                "--json",
            ],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_cli_advances_all_internal_checks_in_one_factory_cas(self) -> None:
        created = self._create(self._complete_ir())
        before_events = self.store.list_events(self.program_id)

        completed = self._run_cli()

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "STOPPED_AT_REAL_GATE")
        self.assertEqual(result["stop_reason"], "WAITING_REQUIREMENT_FREEZE")
        self.assertEqual(result["engine_id"], "GenericTransitionEngine")
        self.assertEqual(len(result["trace"]), 7)
        self.assertTrue(all(item["status"] == "COMPLETED" for item in result["trace"]))
        self.assertFalse(any(item.get("human_gate") for item in result["trace"]))
        self.assertTrue(all(item.get("finding") for item in result["trace"]))
        self.assertTrue(all(item.get("evidence") for item in result["trace"]))
        record = self.store.get_program(self.program_id)
        self.assertEqual(record.revision, created["revision"] + 1)
        self.assertEqual(record.factory_state, "REQUIREMENTS_READBACK_READY")
        events = self.store.list_events(self.program_id)
        self.assertEqual(len(events), len(before_events) + 1)
        self.assertEqual(events[-1]["event_type"], "AUTHORING_AUTO_ADVANCED_TO_REAL_GATE")
        self.assertFalse((self.root / "candidate-must-remain-absent").exists())

    def test_cli_reentry_at_same_real_gate_is_read_only(self) -> None:
        self._create(self._complete_ir())
        first = self._run_cli()
        self.assertEqual(first.returncode, 0, first.stderr)
        database = self.store.database_path
        before_hash = hashlib.sha256(database.read_bytes()).hexdigest()
        before = self.store.get_program(self.program_id)

        second = self._run_cli()

        self.assertEqual(second.returncode, 0, second.stderr)
        result = json.loads(second.stdout)
        self.assertEqual(result["status"], "ALREADY_AT_REAL_GATE")
        after = self.store.get_program(self.program_id)
        self.assertEqual(after.revision, before.revision)
        self.assertEqual(after.state_hash, before.state_hash)
        self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), before_hash)

    def test_blocking_requirement_gap_returns_typed_blocker(self) -> None:
        self._create({})

        completed = self._run_cli()

        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "STOPPED_AT_REAL_GATE")
        self.assertEqual(result["stop_reason"], "BLOCKING_HIGH_CONFLICT")
        blocker = result["blockers"][0]
        self.assertEqual(blocker["blocker_type"], "BLOCKING_HIGH_CONFLICT")
        self.assertEqual(blocker["owner"], "REQUIREMENT_OWNER")
        self.assertTrue(blocker["finding"])
        self.assertTrue(blocker["evidence"])
        self.assertEqual(
            blocker["minimum_return_path"]["intents"],
            ["UPDATE_REQUIREMENTS", "ANSWER"],
        )
        record = self.store.get_program(self.program_id)
        self.assertEqual(record.factory_state, "BLOCKED_REQUIREMENT_GAP")

    def test_mixed_epoch_fails_without_state_mutation(self) -> None:
        created = self._create(
            self._complete_ir(architecture_epoch=4, control_epoch=5)
        )
        before = self.store.get_program(self.program_id)

        completed = self._run_cli()

        self.assertEqual(completed.returncode, 6)
        result = json.loads(completed.stdout)
        self.assertEqual(result["error"]["code"], "CONTRACT_GATE_BLOCKED")
        self.assertEqual(result["error"]["details"]["gate_code"], "MIXED_EPOCH")
        after = self.store.get_program(self.program_id)
        self.assertEqual(after.revision, created["revision"])
        self.assertEqual(after.state_hash, before.state_hash)

    def test_policy_conflict_and_unknown_fail_closed_without_mutation(self) -> None:
        for status, gate_code in (
            ("CONFLICT", "POLICY_CONFLICT"),
            ("UNRECOGNIZED", "POLICY_UNKNOWN"),
        ):
            with self.subTest(status=status):
                self.program_id = f"PROGRAM-SLICE-04-{status}"
                self.store = SQLiteEventStore(
                    self.runs_root / self.program_id / "factory.sqlite3"
                )
                self.service = FactoryService(
                    self.store,
                    spec_root=self.spec_root,
                    runs_root=self.runs_root,
                )
                requirement_ir = self._complete_ir()
                requirement_ir["target"]["authoring_policy_status"] = status
                created = self._create(requirement_ir)
                before = self.store.get_program(self.program_id)

                completed = self._run_cli()

                self.assertEqual(completed.returncode, 6)
                result = json.loads(completed.stdout)
                self.assertEqual(result["error"]["code"], "CONTRACT_GATE_BLOCKED")
                self.assertEqual(result["error"]["details"]["gate_code"], gate_code)
                after = self.store.get_program(self.program_id)
                self.assertEqual(after.revision, created["revision"])
                self.assertEqual(after.state_hash, before.state_hash)

    def test_stale_state_cas_fails_before_authoring_transition(self) -> None:
        created = self._create(self._complete_ir())
        before = self.store.get_program(self.program_id)
        request = self._request("ADVANCE_AUTHORING_UNTIL_GATE", "0" * 64, {})

        with self.assertRaises(StateConflictError):
            self.service.handle_chat_turn(request)

        after = self.store.get_program(self.program_id)
        self.assertEqual(after.revision, created["revision"])
        self.assertEqual(after.state_hash, before.state_hash)

    def test_only_declared_real_risks_create_typed_human_gates(self) -> None:
        cases = (
            ("external_state_required", "WAITING_EXTERNAL_STATE", "EXTERNAL_STATE_OWNER"),
            ("authority_expansion_required", "AUTHORITY_EXPANSION", "AUTHORITY_OWNER"),
            ("irreversible_risk", "IRREVERSIBLE_RISK", "RISK_OWNER"),
        )
        for field, blocker_type, owner in cases:
            with self.subTest(field=field):
                self.program_id = f"PROGRAM-SLICE-04-{field.upper()}"
                self.store = SQLiteEventStore(
                    self.runs_root / self.program_id / "factory.sqlite3"
                )
                self.service = FactoryService(
                    self.store,
                    spec_root=self.spec_root,
                    runs_root=self.runs_root,
                )
                requirement_ir = self._complete_ir()
                requirement_ir["target"][field] = True
                self._create(requirement_ir)

                first = self._run_cli()

                self.assertEqual(first.returncode, 0, first.stderr)
                result = json.loads(first.stdout)
                self.assertEqual(result["stop_reason"], blocker_type)
                blocker = result["blockers"][0]
                self.assertEqual(blocker["blocker_type"], blocker_type)
                self.assertEqual(blocker["owner"], owner)
                self.assertEqual(blocker["evidence"], {"target_field": field, "value": True})
                self.assertEqual(blocker["minimum_return_path"]["intents"], ["REOPEN"])
                self.assertTrue(blocker["human_gate"])
                before = self.store.get_program(self.program_id)

                second = self._run_cli()

                self.assertEqual(second.returncode, 0, second.stderr)
                second_result = json.loads(second.stdout)
                self.assertEqual(second_result["status"], "ALREADY_AT_REAL_GATE")
                after = self.store.get_program(self.program_id)
                self.assertEqual(after.revision, before.revision)
                self.assertEqual(after.state_hash, before.state_hash)


if __name__ == "__main__":
    unittest.main()
