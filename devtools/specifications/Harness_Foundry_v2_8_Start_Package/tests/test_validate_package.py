from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = PACKAGE_ROOT / "tools" / "validate_package.py"
SPEC = importlib.util.spec_from_file_location("validate_package", VALIDATOR_PATH)
if SPEC is None or SPEC.loader is None:  # pragma: no cover - import machinery guard
    raise RuntimeError("Unable to load package validator")
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


def check_by_id(result: dict, check_id: str) -> dict:
    return next(check for check in result["checks"] if check["check_id"] == check_id)


def tree_digest(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


class PackageValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name) / "package"
        shutil.copytree(
            PACKAGE_ROOT,
            self.root,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )

    def test_current_package_passes(self) -> None:
        result = VALIDATOR.validate_package(self.root)
        self.assertEqual("PASS", result["status"], result)
        self.assertFalse(result["writes_performed"])

    def test_invalid_json_is_rejected(self) -> None:
        path = self.root / "templates/target_start_package/LOOP_STATE.template.json"
        path.write_text("{not-json", encoding="utf-8")

        result = VALIDATOR.validate_package(self.root)

        self.assertEqual("FAIL", check_by_id(result, "JSON_AND_JSONL_PARSE")["status"])

    def test_broken_markdown_relative_link_is_rejected(self) -> None:
        readme = self.root / "README.md"
        readme.write_text(
            readme.read_text(encoding="utf-8") + "\n[missing](docs/does-not-exist.md)\n",
            encoding="utf-8",
        )

        result = VALIDATOR.validate_package(self.root)

        self.assertEqual("FAIL", check_by_id(result, "MARKDOWN_RELATIVE_LINKS")["status"])

    def test_wrong_v28_identity_is_rejected(self) -> None:
        path = self.root / "PACKAGE_MANIFEST.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["version"] = "2.7.0"
        path.write_text(json.dumps(manifest), encoding="utf-8")

        result = VALIDATOR.validate_package(self.root)

        self.assertEqual("FAIL", check_by_id(result, "PACKAGE_IDENTITY_V2_8")["status"])

    def test_missing_automation_template_is_rejected(self) -> None:
        path = self.root / "templates/target_start_package/ENGINEERING_PROJECT_DAG.template.json"
        path.unlink()

        result = VALIDATOR.validate_package(self.root)

        self.assertEqual("FAIL", check_by_id(result, "AUTOMATION_TEMPLATES")["status"])

    def test_release_step_deletion_or_reordering_is_rejected(self) -> None:
        path = self.root / "templates/target_start_package/RELEASE_PIPELINE_MANIFEST.template.json"
        pipeline = json.loads(path.read_text(encoding="utf-8"))
        pipeline["steps"][3]["step_id"], pipeline["steps"][4]["step_id"] = (
            pipeline["steps"][4]["step_id"],
            pipeline["steps"][3]["step_id"],
        )
        path.write_text(json.dumps(pipeline), encoding="utf-8")

        result = VALIDATOR.validate_package(self.root)

        self.assertEqual("FAIL", check_by_id(result, "AUTOMATION_TEMPLATES")["status"])

    def test_missing_project_template_is_rejected(self) -> None:
        path = self.root / "templates/project_start_packages/external_lab/PROJECT_CHARTER.template.md"
        path.unlink()

        result = VALIDATOR.validate_package(self.root)

        self.assertEqual("FAIL", check_by_id(result, "PROJECT_START_PACKAGES")["status"])

    def test_authoring_auto_start_is_rejected(self) -> None:
        path = self.root / "templates/target_start_package/START_CONTEXT.template.json"
        context = json.loads(path.read_text(encoding="utf-8"))
        context["auto_start_generated_workpacks"] = True
        path.write_text(json.dumps(context), encoding="utf-8")

        result = VALIDATOR.validate_package(self.root)

        self.assertEqual("FAIL", check_by_id(result, "AUTHORING_DEFAULT_DISABLED")["status"])

    def test_pre_authorized_real_target_install_is_rejected(self) -> None:
        path = self.root / "templates/project_start_packages/main_build/PROJECT_STATE.template.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["real_target_install"]["authorization_ref"] = "AUTH-IMPLICIT"
        state["real_target_install"]["separate_authorization_required"] = False
        path.write_text(json.dumps(state), encoding="utf-8")

        result = VALIDATOR.validate_package(self.root)

        self.assertEqual(
            "FAIL",
            check_by_id(result, "REAL_TARGET_INSTALL_SEPARATE_AUTHORIZATION")["status"],
        )

    def test_relative_executable_or_missing_authorization_is_rejected(self) -> None:
        path = self.root / "templates/project_start_packages/linkage_review/COMMAND_MANIFEST.template.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["commands"][0]["executable"] = "python"
        manifest["commands"][0]["authorization_ref"] = None
        path.write_text(json.dumps(manifest), encoding="utf-8")

        result = VALIDATOR.validate_package(self.root)

        self.assertEqual(
            "FAIL",
            check_by_id(result, "COMMAND_ABSOLUTE_EXECUTABLE_AND_AUTHORIZATION")["status"],
        )

    def test_p3_skip_is_rejected(self) -> None:
        path = self.root / "templates/project_start_packages/main_build/WORKPACK_INDEX.template.json"
        index = json.loads(path.read_text(encoding="utf-8"))
        p4 = next(item for item in index["workpacks"] if item["workpack_id"] == "MB-P4")
        p4["requires"] = ["P2_BUILD_LOCK_VALID"]
        path.write_text(json.dumps(index), encoding="utf-8")

        result = VALIDATOR.validate_package(self.root)

        self.assertEqual("FAIL", check_by_id(result, "P3_NOT_SKIPPABLE")["status"])

    def test_json_cli_writes_only_to_stdout(self) -> None:
        before = tree_digest(self.root)
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"

        completed = subprocess.run(
            [sys.executable, str(self.root / "tools/validate_package.py"), str(self.root), "--json"],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

        payload = json.loads(completed.stdout)
        self.assertEqual(0, completed.returncode, completed.stderr or payload)
        self.assertEqual("PASS", payload["status"], payload)
        self.assertFalse(payload["writes_performed"])
        self.assertEqual("", completed.stderr)
        self.assertEqual(before, tree_digest(self.root))


if __name__ == "__main__":
    unittest.main()
