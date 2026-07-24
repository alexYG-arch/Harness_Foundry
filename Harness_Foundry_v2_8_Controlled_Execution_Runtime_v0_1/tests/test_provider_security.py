"""Codex provider least-privilege profile tests."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from harness_foundry_runtime.providers.codex_workpack_provider import (
    _runtime_python_projection,
    codex_command,
    review_prompt,
)


class ProviderSecurityTests(unittest.TestCase):
    def test_provider_uses_custom_permissions_and_ignores_personal_config(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = root / "candidate"
            workspace = root / "execution/workspace"
            evidence = root / "execution/evidence/NODE"
            for path in (candidate, workspace, evidence):
                path.mkdir(parents=True)
            args = argparse.Namespace(
                codex_path=Path("/Applications/Codex"),
                workspace_root=workspace,
                evidence_root=evidence,
                review_schema=root / "review.schema.json",
            )
            environment = {
                "HF_ALLOWED_READ_ROOTS_JSON": json.dumps(
                    [str(candidate), str(workspace), str(evidence)]
                ),
                "HF_ALLOWED_WRITE_ROOTS_JSON": json.dumps(
                    [str(workspace), str(evidence)]
                ),
            }
            with mock.patch.dict(os.environ, environment, clear=False):
                command, profile_hash = codex_command(
                    args,
                    prompt="controlled",
                    writable_evidence=True,
                )

            joined = "\n".join(command)
            self.assertNotIn("--sandbox", command)
            self.assertIn("--ignore-user-config", command)
            self.assertIn("--ignore-rules", command)
            self.assertIn('default_permissions="hf_controlled"', command)
            self.assertIn(f'"{candidate}" = "read"', joined)
            self.assertIn(f'"{workspace}" = "write"', joined)
            self.assertIn(f'"{evidence}" = "write"', joined)
            self.assertIn(
                f'"{Path.home() / ".codex"}" = "deny"', joined
            )
            self.assertIn(
                f'"{workspace / ".codex"}" = "deny"', joined
            )
            self.assertIn("network = { enabled = false }", joined)
            self.assertRegex(profile_hash, r"^[0-9a-f]{64}$")

    def test_read_only_review_accepts_an_empty_write_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            schema = root / "review.schema.json"
            schema.write_text("{}\n", encoding="utf-8")
            args = argparse.Namespace(
                codex_path=Path("/Applications/Codex"),
                workspace_root=workspace,
                evidence_root=root / "evidence",
                review_schema=schema,
            )
            with mock.patch.dict(
                os.environ,
                {
                    "HF_ALLOWED_READ_ROOTS_JSON": json.dumps(
                        [str(workspace)]
                    ),
                    "HF_ALLOWED_WRITE_ROOTS_JSON": "[]",
                },
                clear=False,
            ):
                command, _profile_hash = codex_command(
                    args,
                    prompt="review",
                    writable_evidence=False,
                )

            self.assertIn("--output-schema", command)
            self.assertIn(str(schema), command)

    def test_permission_profile_reads_the_bound_runtime_python_projection(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir()
            projection = root / "toolchain"
            projection.mkdir()
            python_prefix = root / "python-prefix"
            python_prefix.mkdir()
            python_link = root / "python-current"
            python_link.symlink_to(python_prefix, target_is_directory=True)
            args = argparse.Namespace(
                codex_path=Path("/Applications/Codex"),
                workspace_root=workspace,
                evidence_root=root / "evidence",
                review_schema=root / "review.schema.json",
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "HF_ALLOWED_READ_ROOTS_JSON": json.dumps(
                            [str(workspace)]
                        ),
                        "HF_ALLOWED_WRITE_ROOTS_JSON": json.dumps(
                            [str(workspace)]
                        ),
                    },
                    clear=False,
                ),
                mock.patch(
                    "harness_foundry_runtime.providers."
                    "codex_workpack_provider.sys.base_prefix",
                    str(python_link),
                ),
                mock.patch(
                    "harness_foundry_runtime.providers."
                    "codex_workpack_provider.sys.prefix",
                    str(python_link),
                ),
            ):
                command, _profile_hash = codex_command(
                    args,
                    prompt="python verification",
                    writable_evidence=True,
                    runtime_python_root=projection,
                )

            joined = "\n".join(command)
            self.assertIn(f'"{python_link}" = "read"', joined)
            self.assertIn(
                f'"{python_prefix.resolve()}" = "read"', joined
            )
            self.assertIn(f'"{projection}" = "read"', joined)
            self.assertNotIn(f'"{root}" = "read"', joined)

    def test_runtime_python_projection_is_an_immutable_copy(self) -> None:
        with _runtime_python_projection() as projection:
            source = Path(os.sys.executable)
            projected = projection / "python3"
            self.assertTrue(projected.is_file())
            self.assertFalse(projected.is_symlink())
            self.assertEqual(source.read_bytes(), projected.read_bytes())
            self.assertEqual(projected.stat().st_mode & 0o222, 0)

    def test_current_review_may_clear_an_earlier_review_finding(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = argparse.Namespace(
                node_id="NODE",
                workpack_id="WP",
                workpack_ref=root / "workpack.md",
                candidate_root=root / "candidate",
                workspace_root=root / "workspace",
                evidence_root=root / "evidence",
                execution_root=root / "execution",
            )

            prompt = review_prompt(args)

            self.assertIn(
                "This invocation is the current independent review",
                prompt,
            )
            self.assertIn(
                "Do not require an already successful later review",
                prompt,
            )


if __name__ == "__main__":
    unittest.main()
