"""Relocated generic runtime; synthetic local fixtures, never a real model grant."""

from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

import test_build_runtime as support
from test_build_plan import request_fixture


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("generic_packager", ROOT / "devtools/package_generic_release.py")
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)

# A new interpreter catches eager and indirect imports hidden by a warm test process.
IMPORT_GUARD = '''
import importlib.abc, sys
class RejectLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("harness_foundry_factory."):
            if fullname.split(".", 1)[1] not in ALLOWED:
                raise AssertionError("generic runtime imported " + fullname)
sys.meta_path.insert(0, RejectLegacy())
'''


class GenericDistributionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.archive = self.root / "foundry.zip"
        self.receipt = packager.package(self.archive)
        self.bundle = self.root / "relocated"
        with zipfile.ZipFile(self.archive) as archive:
            archive.extractall(self.bundle)
        self.env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}

    def run_python(self, args, *, data=None):
        return subprocess.run([sys.executable, "-I", "-S", "-B", *args], cwd=self.root,
                              env=self.env, input=data, text=True, capture_output=True, timeout=30)

    def cli(self, command, *args, request=None, expected=0):
        result = self.run_python([str(self.bundle / "tools/hffactory.py"), command, *args, "--json"],
                                 data=json.dumps(request) if request is not None else None)
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
        return json.loads(result.stdout)

    def test_archive_inventory_is_generic_closed_and_has_only_archive_digest(self):
        manifest = json.loads((self.bundle / "PACKAGE_MANIFEST.json").read_text())
        actual = sorted(str(path.relative_to(self.bundle)) for path in self.bundle.rglob("*") if path.is_file())
        self.assertEqual(actual, manifest["files"])
        self.assertEqual(manifest["third_party_python_dependencies"], [])
        self.assertFalse(manifest["acceptance_claimed"])
        self.assertFalse(self.receipt["release_accepted"])
        self.assertNotIn("sha256", json.dumps(manifest))
        self.assertEqual(len(self.receipt["archive_sha256"]), 64)
        for forbidden in ("compiler.py", "validator.py", "store.py", "models.py", "control_kernel.py",
                          "coding_protocol.py", "service.py", "semantic_contracts.py", "constants.py"):
            self.assertFalse((self.bundle / "src/harness_foundry_factory" / forbidden).exists(), forbidden)
        self.assertFalse((self.bundle / "runs").exists())
        self.assertFalse((self.bundle / "spec").exists())

    def test_reproducible_archive_never_overwrites(self):
        second = self.root / "second.zip"
        packager.package(second)
        before = self.archive.read_bytes()
        self.assertEqual(before, second.read_bytes())
        with self.assertRaisesRegex(ValueError, "absent absolute"):
            packager.package(self.archive)
        self.assertEqual(before, self.archive.read_bytes())

    def test_isolated_public_version_compile_and_review_gate(self):
        version = self.cli("version")
        self.assertEqual(version["product_route"], "GENERIC_REVIEWED_BUILD")
        self.assertFalse(version["legacy_specification_required"])
        result = self.cli("compile-build-plan", "--request", "-", request=request_fixture())
        self.assertEqual(result["status"], "PLAN_COMPILED_NOT_AUTHORIZED")
        database = self.root / "unreviewed.sqlite3"
        request = {**request_fixture(), "expected_revision": 0, "idempotency_key": "test"}
        result = self.cli("record-build-plan", "--control-db", str(database), "--request", "-",
                          request=request, expected=2)
        self.assertEqual(result["status"], "ERROR")
        self.assertFalse(database.exists())
        help_result = self.run_python([str(self.bundle / "tools/hffactory.py"), "--help"])
        self.assertEqual(help_result.returncode, 0)
        self.assertNotIn("chat-turn", help_result.stdout)
        self.assertNotIn("generate-candidate", help_result.stdout)

    def test_all_shipped_modules_import_without_legacy_or_external_dependencies(self):
        program = (f"import sys; sys.path.insert(0, {str(self.bundle / 'src')!r}); "
                   f"ALLOWED = {set(packager.MODULES)!r}\n" + IMPORT_GUARD +
                   "import importlib\nfor name in sorted(ALLOWED):\n"
                   "    importlib.import_module('harness_foundry_factory.' + name)\n")
        result = self.run_python(["-c", program])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_source_public_dispatch_uses_same_neutral_modules(self):
        program = (f"import sys; sys.path.insert(0, {str(ROOT / 'src')!r}); "
                   f"ALLOWED = {set(packager.MODULES) | {'entrypoint'}!r}\n" + IMPORT_GUARD +
                   "from harness_foundry_factory.entrypoint import main\n"
                   "raise SystemExit(main(['compile-build-plan', '--request', '-', '--json']))\n")
        result = self.run_python(["-c", program], data=json.dumps(request_fixture()))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "PLAN_COMPILED_NOT_AUTHORIZED")

    def test_relocated_record_prepare_local_fixture_accept_and_resume(self):
        fixture = support.BuildRuntimeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.scope["expires_at"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        database = fixture.root / "portable.sqlite3"
        revision = 0
        key = 0

        def mutate(command, payload):
            nonlocal revision, key
            key += 1
            response = self.cli(command, "--control-db", str(database), "--request", "-",
                request={**payload, "expected_revision": revision, "idempotency_key": f"TEST-{key}"})
            revision = response["stream_revision"]
            return response

        proposal = mutate("record-build-plan", fixture.request)
        source = mutate("capture-build-sources", {"program_id": fixture.program,
            "proposal_event_id": proposal["event_id"], "source_root": str(fixture.source),
            "manifest": [{"source_id": "PROJECT-BRIEF", "path": "brief.md"}]})
        prepared = mutate("prepare-build-authorization", {"program_id": fixture.program,
            "proposal_event_id": proposal["event_id"], "source_event_id": source["event_id"], "scope": fixture.scope})
        mutate("approve-build-authorization", {"program_id": fixture.program,
            "prepared_event_id": prepared["event_id"], "decision": {"action": "APPROVE_BUILD",
            "actor": {"type": "HUMAN_VIA_CODEX_CHAT", "chat_thread_id": "TEST", "turn_id": "TEST-APPROVAL"},
            "user_message": "SYNTHETIC TEST ONLY: not an actual user authorization"}})
        # Only the test process injects a local runner. The distributed CLI has no
        # switch to bypass its native receiver. This is not sandbox/model acceptance.
        program = (f"import sys; sys.path.insert(0, {str(self.bundle / 'src')!r}); "
                   f"ALLOWED = {set(packager.MODULES)!r}\n" + IMPORT_GUARD + '''
import json, subprocess
from harness_foundry_factory.build_runtime import BuildController
from harness_foundry_factory.revision_store import RevisionControlEventStore
calls = []
def fixture_runner(invocation, before_dispatch):
    assert invocation["executor"] == "LOCAL"
    before_dispatch()
    calls.append(invocation["argv"])
    process = subprocess.run(invocation["argv"], cwd=invocation["cwd"], capture_output=True,
                             text=True, timeout=invocation["timeout_seconds"])
    return {"status": "PASS" if process.returncode == 0 else "VALIDATION_FAILED",
            "exit_code": process.returncode, "stdout": process.stdout, "stderr": process.stderr,
            "timed_out": False, "receiver": "TEST_ONLY_NOT_SANDBOX_QUALIFICATION"}
database, program, prepared = json.load(sys.stdin)
controller = BuildController(RevisionControlEventStore(database), program, runner=fixture_runner)
first = controller.advance(prepared)
count = len(calls)
second = controller.advance(prepared)
assert len(calls) == count == 5, calls
assert first["status"] == second["status"] == "PLAN_CHECKS_ACCEPTED", (first, second)
assert not first["harness_e2e_verified"]
print(json.dumps(first))
''')
        result = self.run_python(["-c", program], data=json.dumps([str(database), fixture.program, prepared["event_id"]]))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads((fixture.workspace / "outputs/summary.json").read_text()), {"rows": 3, "invalid": 2})
        view = self.cli("read-build", "--control-db", str(database), "--program-id", fixture.program)
        self.assertEqual([row["status"] for row in view["attempts"]], ["ACCEPTED", "ACCEPTED"])

    def test_every_relative_document_and_skill_link_resolves_in_bundle(self):
        for path in self.bundle.rglob("*.md"):
            for link in re.findall(r"\]\(([^)]+)\)", path.read_text()):
                if "://" in link or link.startswith("#"):
                    continue
                destination = (path.parent / link.split("#", 1)[0]).resolve()
                self.assertTrue(destination.is_relative_to(self.bundle) and destination.is_file(), (path, link))

    def source_copy(self):
        root = self.root / "copy"
        for name in ("resources", "docs", "src", "examples"):
            shutil.copytree(ROOT / name, root / name)
        for name in ("LICENSE", "pyproject.toml", "FACTORY_MANIFEST.json"):
            shutil.copy2(ROOT / name, root / name)
        return root

    def test_undeclared_relative_absolute_and_external_imports_fail_before_publication(self):
        root = self.source_copy()
        module = root / "src/harness_foundry_factory/build_cli.py"
        original = module.read_text()
        for statement in ("from .store import ControlEventStore", "import harness_foundry_factory.store",
                          "from harness_foundry_factory import store", "import requests"):
            module.write_text(original + "\n" + statement + "\n")
            with self.assertRaises(ValueError):
                packager.package(self.root / "invalid.zip", source_root=root)
            self.assertFalse((self.root / "invalid.zip").exists())

    def test_metadata_is_read_from_selected_source_not_building_interpreter(self):
        root = self.source_copy()
        path = root / "src/harness_foundry_factory/identity.py"
        path.write_text(path.read_text().replace('FACTORY_VERSION = "0.2.0"', 'FACTORY_VERSION = "9.8.7"'))
        with self.assertRaisesRegex(ValueError, "product version differs"):
            packager.collect_files(root)
        project = root / "pyproject.toml"
        project.write_text(project.read_text().replace('version = "0.2.0"', 'version = "9.8.7"'))
        product = root / "FACTORY_MANIFEST.json"
        manifest = json.loads(product.read_text())
        manifest["version"] = "9.8.7"
        product.write_text(json.dumps(manifest))
        manifest = json.loads(packager.collect_files(root)["PACKAGE_MANIFEST.json"])
        self.assertEqual(manifest["implementation_version"], "9.8.7")
        product_metadata = json.loads(product.read_text())
        product_metadata["target_protocol_version"] = "9.9"
        product.write_text(json.dumps(product_metadata))
        with self.assertRaisesRegex(ValueError, "protocol version differs"):
            packager.collect_files(root)

    def test_required_resource_missing_or_private_binding_fails(self):
        root = self.source_copy()
        readme = root / "resources/generic_release/README.md"
        readme.write_text(readme.read_text() + "\n/Users/private-person/secret-project\n")
        with self.assertRaisesRegex(ValueError, "private identity"):
            packager.collect_files(root)
        readme.unlink()
        with self.assertRaises(OSError):
            packager.collect_files(root)


if __name__ == "__main__":
    unittest.main()
