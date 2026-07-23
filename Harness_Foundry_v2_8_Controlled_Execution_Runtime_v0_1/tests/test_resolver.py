"""Generic profile resolution and per-Workpack progression tests."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from harness_foundry_runtime.engine import advance_until_gate, status, verify_run
from harness_foundry_runtime.store import RuntimeStore
from harness_foundry_runtime.util import file_sha256, write_json

from support import SyntheticRuntime


class ResolverTests(unittest.TestCase):
    def test_one_profile_drives_all_workpacks_until_human_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = SyntheticRuntime(
                Path(temporary), multi_workpack=True
            )
            fixture.bootstrap()
            state = RuntimeStore(fixture.execution).load_state()
            executable = str(Path(sys.executable))
            marker = (
                "{{HF_EXECUTION_ROOT}}/workspace/"
                "{{HF_WORKPACK_ID}}.done"
            )
            check_code = (
                "from pathlib import Path;"
                f"raise SystemExit(0 if Path({marker!r}).is_file() else 9)"
            )
            commands = [
                {
                    "command_id": (
                        "{{HF_NODE_ID}}-{{HF_WORKPACK_ID}}-EXECUTE"
                    ),
                    "stage": "execute",
                    "executable_abs": executable,
                    "executable_sha256": "AUTO",
                    "argv": [
                        executable,
                        "-c",
                        (
                            "from pathlib import Path;"
                            f"Path({marker!r}).write_text('ok')"
                        ),
                    ],
                    "cwd_abs": "{{HF_EXECUTION_ROOT}}/workspace",
                    "allowed_write_roots": [
                        "{{HF_EXECUTION_ROOT}}/workspace"
                    ],
                    "environment": {},
                    "expected_exit_codes": [0],
                    "timeout_seconds": 5,
                    "shell": False,
                    "idempotent": True,
                    "independent_review": False,
                    "executor_identity": "WORKPACK_EXECUTOR",
                    "review_target_mode": "NOT_APPLICABLE",
                    "failure_error_code": "COMMAND_EXIT_NONZERO",
                    "side_effect_cleanup_confirmed": False,
                },
                {
                    "command_id": (
                        "{{HF_NODE_ID}}-{{HF_WORKPACK_ID}}-POSTFLIGHT"
                    ),
                    "stage": "postflight",
                    "executable_abs": executable,
                    "executable_sha256": file_sha256(Path(executable)),
                    "argv": [executable, "-c", check_code],
                    "cwd_abs": "{{HF_EXECUTION_ROOT}}/workspace",
                    "allowed_write_roots": [
                        "{{HF_EXECUTION_ROOT}}/workspace"
                    ],
                    "environment": {},
                    "expected_exit_codes": [0],
                    "timeout_seconds": 5,
                    "shell": False,
                    "idempotent": True,
                    "independent_review": False,
                    "executor_identity": "WORKPACK_EXECUTOR",
                    "review_target_mode": "NOT_APPLICABLE",
                    "failure_error_code": "ACCEPTANCE_FAILED",
                    "side_effect_cleanup_confirmed": False,
                },
                {
                    "command_id": (
                        "{{HF_NODE_ID}}-{{HF_WORKPACK_ID}}-REVIEW"
                    ),
                    "stage": "review",
                    "executable_abs": executable,
                    "executable_sha256": "AUTO",
                    "argv": [executable, "-c", check_code],
                    "cwd_abs": "{{HF_EXECUTION_ROOT}}/workspace",
                    "allowed_write_roots": [],
                    "environment": {},
                    "expected_exit_codes": [0],
                    "timeout_seconds": 5,
                    "shell": False,
                    "idempotent": True,
                    "independent_review": True,
                    "executor_identity": "INDEPENDENT_REVIEWER",
                    "review_target_mode": "READ_ONLY",
                    "failure_error_code": "REVIEW_FAILED",
                    "side_effect_cleanup_confirmed": False,
                },
            ]
            bundle_path = fixture.root / "AUTOMATION_RESOLVER_BUNDLE.json"
            write_json(
                bundle_path,
                {
                    "schema_version": "1.0",
                    "resolver_kind": (
                        "WORKPACK_AUTOMATION_RESOLVER_BUNDLE"
                    ),
                    "program_id": fixture.program_id,
                    "epoch_id": state["epoch_id"],
                    "candidate_content_sha256": (
                        state["candidate_content_sha256"]
                    ),
                    "node_ids": ["NODE_A", "NODE_B"],
                    "default_profile_id": "PYTHON_WORKPACK",
                    "profiles": {
                        "PYTHON_WORKPACK": {"commands": commands}
                    },
                },
            )

            completed = subprocess.run(
                [
                    str(
                        fixture.execution
                        / "control_plane/bin/hfdriver"
                    ),
                    "resolve-overlays",
                    "--execution-root",
                    str(fixture.execution),
                    "--bundle",
                    str(bundle_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            resolution = json.loads(completed.stdout)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(resolution["status"], "PASS")
            self.assertFalse(resolution["execution_authority_granted"])
            self.assertFalse(resolution["commands_executed"])
            self.assertEqual(
                status(fixture.execution)["effective_mode"],
                "A1_PLAN_ONLY",
            )
            fixture.apply_authorization(
                resolution["command_manifests"],
                node_ids=["NODE_A", "NODE_B"],
            )

            result = advance_until_gate(fixture.execution)

            self.assertEqual(result["status"], "STOPPED_AT_GATE")
            self.assertEqual(result["transitions_committed"], 2)
            self.assertEqual(
                status(fixture.execution)["completed_workpacks"],
                ["WP-NODE_A-1", "WP-NODE_A-2", "WP-NODE_B"],
            )
            promotion_events = [
                event
                for event in RuntimeStore(fixture.execution).events()
                if event["event_type"] == "WORKPACK_PROMOTED"
            ]
            self.assertEqual(len(promotion_events), 3)
            self.assertEqual(
                result["stop"]["human_gate_id"],
                "WAIT_REAL_TARGET_INSTALL_AUTHORIZATION",
            )
            self.assertEqual(
                verify_run(fixture.execution)["status"], "PASS"
            )


if __name__ == "__main__":
    unittest.main()
