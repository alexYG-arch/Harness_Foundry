"""Finite local fixture interleavings; no model or OS-sandbox qualification."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

from tests.python_fixture import python_fixture_header

import test_build_runtime as support
from harness_foundry_factory.build_reconciliation import reconcile_build_observations
from harness_foundry_factory.build_runtime import BuildController, NativeBuildRunner
from harness_foundry_factory.build_types import RequestValidationError


class BuildObservationRaceTests(unittest.TestCase):
    def setUp(self):
        self.f = support.BuildRuntimeTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        receiver = self.f.root / "fixture-only-local-receiver"
        receiver.write_text(python_fixture_header() + '''import subprocess, sys
args = sys.argv[1:]
if args == ["sandbox", "--help"]:
    print("--permission-profile --include-managed-config --cd [COMMAND]")
else:
    assert args[0] == "sandbox"
    sys.exit(subprocess.call(args[args.index("--") + 1:]))
''')
        receiver.chmod(0o700)
        self.f.scope["codex_executable"] = str(receiver)
        self.f.prepare()
        self.native = NativeBuildRunner()
        self.invocations = []

    def test_reconcile_before_original_observation_retains_one_record_and_never_replays(self):
        f = self.f
        summaries = []
        def interleaved(invocation, before_dispatch):
            self.invocations.append((invocation["workpack_id"], invocation["phase"], invocation["case_id"]))
            result = self.native(invocation, before_dispatch)
            if not summaries:
                # The native receiver has durable result/capture and has closed
                # its process, but the original controller has not appended it.
                self.assertTrue((Path(invocation["observation_root"]) / "capture.json").is_file())
                self.assertFalse(f.events("BUILD_COMMAND_OBSERVED"))
                summaries.append(reconcile_build_observations(f.store, f.program, f.prepared_id,
                    **f.kwargs("interleaved-reconcile")))
            return {**result, "late_receiver_diagnostic": "must not replace the earlier durable record"}
        controller = BuildController(f.store, f.program, runner=interleaved, clock=support.CLOCK)
        first = controller.advance(f.prepared_id, advance_mode="ONE_ATTEMPT")
        self.assertEqual(first["status"], "HELD_UNRESOLVED_ATTEMPT", first)
        self.assertEqual(first["accepted_workpacks"], [])
        self.assertEqual(len(self.invocations), 1)
        self.assertEqual(len(f.events("BUILD_ATTEMPT_STARTED")), 1)
        observed = f.events("BUILD_COMMAND_OBSERVED")
        self.assertEqual(len(observed), 1)
        original = deepcopy(observed[0])
        self.assertNotIn("late_receiver_diagnostic", original["payload"]["result"])
        self.assertEqual(summaries[0]["payload"]["recovered_command_ids"], [original["payload"]["command_id"]])
        self.assertEqual(f.events("BUILD_ATTEMPT_FINISHED")[0]["payload"]["status"], "UNKNOWN_SIDE_EFFECT")
        resumed = controller.advance(f.prepared_id)
        self.assertEqual(resumed["status"], "PLAN_CHECKS_ACCEPTED", resumed)
        self.assertEqual(len(self.invocations), 5, "recovery runs only the undispatched checks and second task")
        self.assertEqual(len(f.events("BUILD_ATTEMPT_STARTED")), 2, "the first production attempt stays spent exactly once")
        observed = f.events("BUILD_COMMAND_OBSERVED")
        self.assertEqual(len(observed), 5)
        self.assertEqual(len({row["payload"]["command_id"] for row in observed}), 5)
        self.assertEqual(observed[0], original)
        self.assertEqual(controller.advance(f.prepared_id)["status"], "PLAN_CHECKS_ACCEPTED")
        self.assertEqual(len(self.invocations), 5, "accepted work is not repeated")

    def test_existing_command_with_conflicting_binding_is_not_silently_reused(self):
        f = self.f
        controller = BuildController(f.store, f.program, runner=self.native, clock=support.CLOCK)
        self.assertEqual(controller.advance(f.prepared_id, advance_mode="ONE_ATTEMPT")["attempt_status"], "ACCEPTED")
        observed = f.events("BUILD_COMMAND_OBSERVED")[0]
        before = deepcopy(f.events())
        for field, value in (("observation_root", str(f.root / "wrong-root")),
                             ("attempt_id", "OTHER-ATTEMPT"), ("executor", "CODEX")):
            with self.subTest(field=field):
                contradictory = {**observed["payload"], field: value}
                with self.assertRaises(RequestValidationError):
                    controller._record_observation("BUILD_COMMAND_OBSERVED", contradictory,
                                                   "late-conflicting-observation-" + field)
                self.assertEqual(f.events(), before)


if __name__ == "__main__":
    unittest.main()
