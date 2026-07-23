"""Resolved Command Manifest overlay registration tests."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from harness_foundry_runtime.engine import (
    authorization_plan,
    register_command_overlays,
    status,
    verify_run,
)
from harness_foundry_runtime.util import file_sha256, write_json

from support import SyntheticRuntime


class CommandOverlayTests(unittest.TestCase):
    def test_registration_hash_binds_manifests_without_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            source = fixture.make_manifest("NODE_A")
            bundle_path = fixture.root / "COMMAND_OVERLAY_BUNDLE.json"
            state = status(fixture.execution)
            write_json(
                bundle_path,
                {
                    "schema_version": "1.0",
                    "overlay_kind": "RESOLVED_COMMAND_OVERLAY_BUNDLE",
                    "program_id": fixture.program_id,
                    "epoch_id": state["epoch_id"],
                    "candidate_content_sha256": (
                        json.loads(
                            fixture.handoff_path.read_text(
                                encoding="utf-8"
                            )
                        )["candidate_content_sha256"]
                    ),
                    "manifests": {
                        "NODE_A": json.loads(
                            source.read_text(encoding="utf-8")
                        )
                    },
                },
            )

            result = register_command_overlays(
                fixture.execution, bundle_path
            )
            binding = result["command_manifests"]["NODE_A"]

            self.assertEqual(result["status"], "PASS")
            self.assertFalse(result["execution_authority_granted"])
            self.assertFalse(result["commands_executed"])
            self.assertEqual(
                file_sha256(Path(binding["path"])),
                binding["sha256"],
            )
            self.assertEqual(
                status(fixture.execution)["effective_mode"],
                "A1_PLAN_ONLY",
            )
            self.assertEqual(verify_run(fixture.execution)["status"], "PASS")

    def test_authorization_rejects_an_unregistered_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            manifest = fixture.make_manifest("NODE_A")
            request_path = fixture.root / "AUTHORIZATION_REQUEST.json"
            write_json(
                request_path,
                {
                    "level": "A3_PROGRAM_BOUNDED",
                    "dag_node_ids": ["NODE_A"],
                    "workpack_ids": ["WP-NODE_A"],
                    "command_manifests": {
                        "NODE_A": {
                            "path": str(manifest),
                            "sha256": file_sha256(manifest),
                        }
                    },
                    "allowed_write_roots": [str(fixture.workspace)],
                    "environment_ids": ["TEST-ENV"],
                    "expires_at": "2099-01-01T00:00:00Z",
                    "max_transitions": 1,
                    "max_loop_rounds": 1,
                    "max_wall_time_seconds": 60,
                },
            )

            result = authorization_plan(
                fixture.execution, request_path
            )
            codes = {
                item["code"] for item in result["blocking_findings"]
            }

            self.assertEqual(result["status"], "FAIL")
            self.assertIn("COMMAND_MANIFEST_NOT_REGISTERED", codes)

    def test_registration_rejects_cross_epoch_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(Path(temporary))
            fixture.bootstrap()
            source = fixture.make_manifest("NODE_A")
            bundle_path = fixture.root / "COMMAND_OVERLAY_BUNDLE.json"
            state = status(fixture.execution)
            write_json(
                bundle_path,
                {
                    "schema_version": "1.0",
                    "overlay_kind": "RESOLVED_COMMAND_OVERLAY_BUNDLE",
                    "program_id": fixture.program_id,
                    "epoch_id": "EPOCH-OTHER",
                    "candidate_content_sha256": (
                        json.loads(
                            fixture.handoff_path.read_text(
                                encoding="utf-8"
                            )
                        )["candidate_content_sha256"]
                    ),
                    "manifests": {
                        "NODE_A": json.loads(
                            source.read_text(encoding="utf-8")
                        )
                    },
                },
            )

            result = register_command_overlays(
                fixture.execution, bundle_path
            )
            codes = {
                item["code"] for item in result["blocking_findings"]
            }

            self.assertEqual(result["status"], "FAIL")
            self.assertIn("COMMAND_OVERLAY_BINDING_MISMATCH", codes)
            self.assertEqual(
                state["runtime_revision"],
                status(fixture.execution)["runtime_revision"],
            )
