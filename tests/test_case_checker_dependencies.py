"""Per-Case checker views; disposable local processes, no model or business state."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from harness_foundry_factory.build_runtime import prepare_build_authorization, approve_build_authorization
from harness_foundry_factory.build_types import RequestValidationError
from harness_foundry_factory.build_rebind import _check_signature
from harness_foundry_factory.build_state import project_budget_attempts, attempt_budget
from harness_foundry_factory.build_entrypoint import read_build
from harness_foundry_factory.build_correction import derive_checker_authorization
from harness_foundry_factory.verification_snapshot import snapshot_verifier
import test_build_correction as corrections
import test_build_resources as resources
import test_build_runtime as support
import test_build_preview as preview_support

PREFIX = r'''
import json, os, sys
from pathlib import Path
root = Path(os.environ["FOUNDRY_VERIFIER_ROOT"])
sys.path.insert(0, str(root))
from helpers.oracle import marker
case_id = os.environ["FOUNDRY_CASE_ID"]
assert marker == "approved"
assert json.loads((root / ("inputs/" + case_id + ".json")).read_text()) == {"case": case_id}
assert (root / "shared.txt").read_text() == "shared"
assert not (root / "undeclared.py").exists()
assert len(list((root / "inputs").glob("*.json"))) == 1, "neighbor Case leaked into runtime view"
'''

def case_fixture(owner):
    holder = resources.BuildResourceIntegrationTests()
    owner.addCleanup(holder.doCleanups)
    f = holder.fixture()
    f.scope["max_attempts"] = 20
    f.scope["max_task_attempts"] = 10
    (f.verifier / "check.py").write_text(PREFIX + resources.RESOURCE_CHECKER)
    (f.verifier / "helpers").mkdir()
    (f.verifier / "helpers/__init__.py").write_text("")
    (f.verifier / "helpers/oracle.py").write_text('marker = "approved"\n')
    (f.verifier / "shared.txt").write_text("shared")
    (f.verifier / "inputs").mkdir()
    mapping = {}
    for task in f.plan["workpacks"]:
        for check in task["verification"]:
            name = "inputs/" + check["case_id"] + ".json"
            (f.verifier / name).write_text(json.dumps({"case": check["case_id"]}))
            mapping[check["case_id"]] = [name]
    f.scope["verification_resources"].update(
        checker_files=["helpers/__init__.py", "helpers/oracle.py", "shared.txt"],
        case_checker_files=mapping)
    return f

class CaseCheckerDependencyTests(unittest.TestCase):
    def fixture(self):
        return case_fixture(self)

    def rebind(self, f, *, origin=None, approve=True, key="next"):
        new = prepare_build_authorization(f.store, f.program, f.proposal_id, f.source_id,
            f.scope, rebind_from=origin or f.prepared_id, **f.kwargs(key + "-prepare"))["event_id"]
        if approve:
            approve_build_authorization(f.store, f.program, new,
                human_message_ref="TEST disposable host decision", **f.kwargs(key + "-approve"))
        return new

    def test_actual_view_and_command_binding_exclude_neighbor_files(self):
        f = self.fixture()
        (f.verifier / "undeclared.py").write_text("raise RuntimeError('development only')")
        f.prepare()
        self.assertEqual(f.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        checks = [e["payload"] for e in f.events("BUILD_COMMAND_OBSERVED")
                  if e["payload"]["phase"] == "VERIFICATION"]
        self.assertEqual(len(checks), 3)
        for row in checks:
            binding = row["resource_binding"]
            expected = {"check.py", "helpers/__init__.py", "helpers/oracle.py", "shared.txt",
                        "inputs/" + row["case_id"] + ".json"}
            self.assertEqual(set(binding["verifier_files"]), expected)
            root = Path(binding["verifier_root"])
            self.assertEqual({p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}, expected)
            self.assertNotEqual(root, f.verifier)
            self.assertEqual(row["result"]["resource_cleanup"]["status"], "CLEANED")
        self.assertEqual(len({r["resource_binding"]["verifier_root"] for r in checks}), 3)

    def test_report_only_dependency_change_preserves_other_acceptance(self):
        f = self.fixture(); f.prepare()
        self.assertEqual(f.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        old = deepcopy(f.events("BUILD_ATTEMPT_FINISHED"))
        path = f.verifier / "inputs/REPORT-COUNT.json"
        path.write_text(path.read_text() + "\n")
        new = self.rebind(f)
        before = len(f.runner.invocations)
        self.assertEqual(f.controller().advance(new)["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual([(c["phase"], c["case_id"]) for c in f.runner.invocations[before:]],
                         [("VERIFICATION", "REPORT-COUNT")])
        self.assertEqual(f.events("BUILD_ATTEMPT_FINISHED")[:2], old)
        used = attempt_budget(f.scope, list(project_budget_attempts(f.events(), new).values()))
        self.assertEqual(used["attempts_consumed"], 3)

    def test_shared_dependency_change_rechecks_all_dependents_without_production(self):
        f = self.fixture(); f.prepare(); self.assertEqual(f.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        path = f.verifier / "helpers/oracle.py"
        path.write_text(path.read_text() + "# adapter comment\n")
        new = self.rebind(f); before = len(f.runner.invocations)
        self.assertEqual(f.controller().advance(new)["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual([c["phase"] for c in f.runner.invocations[before:]], ["VERIFICATION"] * 3)

    def test_empty_and_partial_maps_keep_entry_and_shared_inputs(self):
        for mapping in ({}, {"READ-ROWS": []}):
            with self.subTest(mapping=mapping):
                f = self.fixture()
                f.scope["verification_resources"]["case_checker_files"] = mapping
                (f.verifier / "check.py").write_text(resources.RESOURCE_CHECKER)
                f.prepare(); self.assertEqual(f.advance()["status"], "PLAN_CHECKS_ACCEPTED")
                for event in f.events("BUILD_COMMAND_OBSERVED"):
                    if event["payload"]["phase"] == "VERIFICATION":
                        self.assertEqual(set(event["payload"]["resource_binding"]["verifier_files"]),
                            {"check.py", "shared.txt", "helpers/__init__.py", "helpers/oracle.py"})

    def test_unknown_case_invalid_path_or_missing_file_cannot_prepare(self):
        for mapping in ({"UNKNOWN": []}, {"READ-ROWS": ["../outside"]},
                        {"READ-ROWS": ["missing.json"]}, {"READ-ROWS": "input.json"},
                        {"READ-ROWS": ["shared.txt", "shared.txt"]}):
            with self.subTest(mapping=mapping):
                f = self.fixture()
                f.scope["verification_resources"]["case_checker_files"] = mapping
                with self.assertRaises((RequestValidationError, FileNotFoundError)):
                    f.prepare()
                self.assertFalse(f.events("BUILD_AUTHORIZATION_PREPARED"))
                self.assertEqual(f.runner.invocations, [])

    def test_shared_and_case_duplicates_are_loaded_once(self):
        f = self.fixture()
        f.scope["verification_resources"]["case_checker_files"]["READ-ROWS"] += ["shared.txt"]
        f.prepare(); self.assertEqual(f.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        first = next(e["payload"] for e in f.events("BUILD_COMMAND_OBSERVED") if e["payload"]["phase"] == "VERIFICATION")
        self.assertEqual(len(first["resource_binding"]["verifier_files"]), 5)

    def test_missing_dependency_cannot_be_borrowed_from_source_neighbor_or_product(self):
        f = self.fixture()
        config = f.scope["verification_resources"]
        config["checker_files"] = ["shared.txt"]
        for case_id in ("REJECT-MALFORMED", "REPORT-COUNT"):
            config["case_checker_files"][case_id] += ["helpers/__init__.py", "helpers/oracle.py"]
        shutil.copytree(f.verifier / "helpers", f.workspace / "helpers")
        f.prepare()
        result = f.controller().advance(f.prepared_id, advance_mode="ONE_ATTEMPT")
        self.assertEqual(result["attempt_status"], "BLOCKED", result)
        commands = f.events("BUILD_COMMAND_OBSERVED")
        self.assertEqual(len(commands), 2)
        self.assertIn("ModuleNotFoundError", commands[-1]["payload"]["result"]["stderr"])
        self.assertEqual(len(f.events("BUILD_ATTEMPT_STARTED")), 1)

    def test_spaces_package_imports_and_inside_link_preserve_bound_bytes(self):
        f = self.fixture()
        renamed = f.root / "检查 source with spaces"; f.verifier.rename(renamed)
        f.verifier = renamed; f.scope["verification_root"] = str(renamed)
        real = renamed / "helpers/real.py"
        (renamed / "helpers/oracle.py").rename(real)
        (renamed / "helpers/oracle.py").symlink_to("real.py")
        f.prepare(); self.assertEqual(f.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        prepared = f.events("BUILD_AUTHORIZATION_PREPARED")[0]["payload"]
        for view in prepared["verifier_source"]["case_views"].values():
            self.assertFalse((Path(view["runtime_root"]) / "helpers/oracle.py").is_symlink())
        self.assertEqual(f.scope["executables"]["python"], support.sys.executable)

    def test_view_mutation_holds_before_production(self):
        f = self.fixture(); f.prepare()
        prepared = f.events("BUILD_AUTHORIZATION_PREPARED")[0]["payload"]
        view = Path(prepared["verifier_source"]["case_views"]["READ-ROWS"]["runtime_root"])
        path = view / "helpers/oracle.py"; path.chmod(0o644); path.write_text('marker = "wrong"')
        result = f.advance()
        self.assertEqual(result["status"], "BUILD_STOPPED", result)
        self.assertIn("checker bytes changed", result["reason"])
        self.assertEqual(f.runner.invocations, [])

    def test_case_map_assignment_changes_signature_even_if_union_is_unchanged(self):
        f = self.fixture(); f.prepare()
        old = f.events("BUILD_AUTHORIZATION_PREPARED")[0]["payload"]
        new = deepcopy(old)
        mapping = new["scope"]["verification_resources"]["case_checker_files"]
        mapping["READ-ROWS"], mapping["REJECT-MALFORMED"] = mapping["REJECT-MALFORMED"], mapping["READ-ROWS"]
        self.assertNotEqual(_check_signature(old, f.plan["workpacks"][0]),
                            _check_signature(new, f.plan["workpacks"][0]))
        self.assertEqual(_check_signature(old, f.plan["workpacks"][1]),
                         _check_signature(new, f.plan["workpacks"][1]))

    def test_captured_report_recovery_reuses_original_view_without_dispatch(self):
        f = self.fixture(); f.prepare()
        crashed = []
        def after(invocation, result):
            if invocation["phase"] == "VERIFICATION" and not crashed:
                crashed.append(invocation["command_id"])
                raise support.InjectedControllerCrash()
        f.runner.after_run = after
        with self.assertRaises(support.InjectedControllerCrash):
            f.advance()
        before = len(f.runner.invocations)
        original = f.events("BUILD_COMMAND_PLANNED")[-1]["payload"]
        f.runner.after_run = None
        self.assertEqual(f.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(f.runner.invocations) - before, 3)
        recovered = [e["payload"] for e in f.events("BUILD_COMMAND_OBSERVED")
                     if e["payload"]["command_id"] == crashed[0]]
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["resource_binding"], original["resource_binding"])
        count = len(f.runner.invocations)
        for _ in range(2):
            self.assertEqual(f.advance()["status"], "PLAN_CHECKS_ACCEPTED")
            read_build(f.store.database_path, f.program)
        self.assertEqual(len(f.runner.invocations), count)
        self.assertEqual(len(f.events("BUILD_ATTEMPT_STARTED")), 2)

    def test_same_scope_mapping_reorganization_then_ordinary_rebind_preserves_charges(self):
        f = self.fixture(); f.prepare(); self.assertEqual(f.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        old_id = f.prepared_id
        # Equivalent movement of a helper from shared to every explicit Case.
        config = f.scope["verification_resources"]
        config["checker_files"].remove("shared.txt")
        for selected in config["case_checker_files"].values():
            selected.append("shared.txt")
        path = f.verifier / "helpers/oracle.py"
        path.write_text(path.read_text() + "# independently reviewed adapter change\n")
        new = self.rebind(f, approve=False)
        holder = corrections.CheckerCorrectionTests(); holder.f = f
        evidence = holder.evidence(old_id, new)
        derive_checker_authorization(f.store, f.program, new, evidence=evidence, **f.kwargs("derive"))
        count = len(f.runner.invocations)
        self.assertEqual(f.controller().advance(new)["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual([c["phase"] for c in f.runner.invocations[count:]], ["VERIFICATION"] * 3)
        self.assertEqual(attempt_budget(f.scope, list(project_budget_attempts(f.events(), new).values()))["attempts_consumed"], 2)
        path.write_text(path.read_text() + "# later ordinary rebind\n")
        latest = self.rebind(f, origin=new, key="ordinary")
        self.assertEqual(f.controller().advance(latest)["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(attempt_budget(f.scope, list(project_budget_attempts(f.events(), latest).values()))["attempts_consumed"], 4)
        frozen_events = deepcopy(f.events()); count = len(f.runner.invocations)
        for _ in range(2):
            read_build(f.store.database_path, f.program)
            self.assertEqual(f.controller().advance(latest)["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(f.events(), frozen_events)
        self.assertEqual(len(f.runner.invocations), count)

    def test_case_cleanup_warning_keeps_acceptance_and_report_recovery_without_replay(self):
        f = self.fixture(); f.prepare()
        remove = shutil.rmtree
        resource_root = Path(f.scope["verification_resources"]["root"])
        def cleanup_failure(path, *args, **kwargs):
            if Path(path).is_relative_to(resource_root):
                raise PermissionError("TEST isolated cleanup failure")
            return remove(path, *args, **kwargs)
        with patch("harness_foundry_factory.verification_resources.shutil.rmtree", side_effect=cleanup_failure):
            self.assertEqual(f.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        checks = [e["payload"] for e in f.events("BUILD_COMMAND_OBSERVED") if e["payload"]["phase"] == "VERIFICATION"]
        self.assertEqual(len(checks), 3)
        for row in checks:
            self.assertEqual(row["result"]["status"], "PASS")
            self.assertEqual(row["result"]["resource_cleanup"]["status"], "CLEANUP_WARNING")
            self.assertEqual(row["case_verifier_binding"]["verifier_files"], row["resource_binding"]["verifier_files"])
        count = len(f.runner.invocations); events = deepcopy(f.events())
        with patch("harness_foundry_factory.resource_observation.cleanup_resources", side_effect=AssertionError("no repeated cleanup")):
            for _ in range(2):
                read_build(f.store.database_path, f.program)
                self.assertEqual(f.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(f.runner.invocations), count)
        self.assertEqual(f.events(), events)

    def test_repeated_case_across_tasks_keeps_each_effective_entrypoint(self):
        for different_entry in (False, True):
            with self.subTest(different_entry=different_entry):
                f = self.fixture()
                task = f.plan['workpacks'][1]; task['atom_ids'].append('REQ-READ')
                check = deepcopy(task['verification'][0]); check['case_id'] = 'READ-ROWS'
                if different_entry:
                    check['argv'] = [x.replace('verifier://check.py', 'verifier://report-check.py') for x in check['argv']]
                    (f.verifier/'report-check.py').write_bytes((f.verifier/'check.py').read_bytes())
                task['verification'].append(check)
                f.prepare(); self.assertEqual(f.advance()['status'], 'PLAN_CHECKS_ACCEPTED')
                checks = [e['payload'] for e in f.events('BUILD_COMMAND_OBSERVED')
                          if e['payload']['phase']=='VERIFICATION' and e['payload']['case_id']=='READ-ROWS']
                self.assertEqual(len(checks), 2)
                first, second = [c['case_verifier_binding'] for c in checks]
                self.assertEqual(first['verifier_root']==second['verifier_root'], not different_entry)
                self.assertIn('check.py', first['verifier_files'])
                if different_entry:
                    self.assertIn('report-check.py', second['verifier_files'])
                    self.assertNotIn('check.py', second['verifier_files'])
                    path=f.verifier/'report-check.py'; path.write_text(path.read_text()+'\n# equivalent report-entry change\n')
                    new=self.rebind(f); before=len(f.runner.invocations)
                    self.assertEqual(f.controller().advance(new)['status'], 'PLAN_CHECKS_ACCEPTED')
                    self.assertEqual([(c['phase'],c['workpack_id']) for c in f.runner.invocations[before:]],
                                     [('VERIFICATION',task['workpack_id'])]*2)


    def test_old_global_snapshot_rebind_to_case_views_requires_fresh_checks(self):
        f = self.fixture()
        mapping = f.scope["verification_resources"].pop("case_checker_files")
        f.scope["verification_resources"]["checker_files"] += [n for v in mapping.values() for n in v]
        (f.verifier / "check.py").write_text(resources.RESOURCE_CHECKER)
        f.prepare(); self.assertEqual(f.advance()["status"], "PLAN_CHECKS_ACCEPTED")
        original = deepcopy(f.events())
        f.scope["verification_resources"]["case_checker_files"] = {}
        new = self.rebind(f); count = len(f.runner.invocations)
        self.assertEqual(f.controller().advance(new)["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual([c["phase"] for c in f.runner.invocations[count:]], ["VERIFICATION"] * 3)
        self.assertEqual(f.events()[:len(original)], original)

    def test_case_mapping_keeps_tool_profile_and_public_input_invalidation(self):
        f = self.fixture(); f.prepare()
        prepared = f.events("BUILD_AUTHORIZATION_PREPARED")[0]["payload"]
        task = f.plan["workpacks"][0]
        original = _check_signature(prepared, task)
        for kind in ("tool", "profile", "input"):
            with self.subTest(kind=kind):
                changed, selected = deepcopy(prepared), deepcopy(task)
                if kind == "tool":
                    changed["scope"]["executables"]["python"] += "-other-version"
                elif kind == "profile":
                    ref = selected["verification"][0]["resource_profile_ref"]
                    changed["scope"]["verification_resources"]["profiles"][ref]["required_checks"].append("new-obligation")
                else:
                    selected["verification"][0]["argv"].append("different-public-input")
                self.assertNotEqual(original, _check_signature(changed, selected))

    def test_preview_reuses_case_snapshot_and_rejects_changed_view_before_registration(self):
        holder = preview_support.BuildPreviewTests(); holder.setUp()
        self.addCleanup(holder.doCleanups)
        original_confirm = holder.confirm
        def configure(preview=None):
            holder.f.scope["verification_resources"]["case_checker_files"] = {"READ-ROWS": ["only.txt"]}
            (holder.f.verifier / "only.txt").write_text("private input")
            return original_confirm(preview)
        holder.confirm = configure
        request = holder.resource_preview()
        prepared = json.loads(holder.path.read_text())["prepared"]
        views = prepared["verifier_source"]["case_views"]
        root = Path(views["READ-ROWS"]["runtime_root"])
        before = sorted(root.parent.parent.rglob("*"))
        changed = root / "only.txt"; captured = changed.read_bytes()
        changed.chmod(0o644); changed.write_bytes(b"wrong input")
        with self.assertRaises(RequestValidationError):
            holder.materialize(request)
        self.assertFalse(holder.db.exists())
        changed.write_bytes(captured)
        result = holder.materialize(request)
        self.assertEqual(before, sorted(root.parent.parent.rglob("*")))
        actual = next(e["payload"] for e in holder.events() if e["event_id"] == result["prepared_event_id"])
        self.assertEqual(actual["verifier_source"]["case_views"], views)
        self.assertEqual(holder.materialize(request), result)

    def test_snapshot_copy_failure_removes_incomplete_views_without_events(self):
        f = self.fixture()
        original = shutil.copyfile
        def interrupted(source, target, *args, **kwargs):
            if any(part.startswith("CASES-VERIFIER-") for part in Path(target).parts):
                raise OSError("test-only capture failure")
            return original(source, target, *args, **kwargs)
        before = deepcopy(f.events())
        with patch("harness_foundry_factory.verification_snapshot.shutil.copyfile", side_effect=interrupted):
            with self.assertRaisesRegex(OSError, "capture failure"):
                snapshot_verifier(f.store, f.plan, f.scope)
        self.assertEqual(f.events(), before)
        self.assertEqual(list(f.store.database_path.with_suffix(".verifiers").iterdir()), [])
        self.assertEqual(f.runner.invocations, [])
