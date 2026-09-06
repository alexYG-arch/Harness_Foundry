"""TEST ONLY: non-idempotent local effect and a restartable kernel client.

This is not a production command adapter, Codex execution or sandbox proof.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from harness_foundry_factory.control_kernel import GenericTransitionEngine
from harness_foundry_factory.store import ControlEventStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    effect = sub.add_parser("effect")
    effect.add_argument("marker", type=Path)
    effect.add_argument("exit_code", type=int)
    execute = sub.add_parser("execute")
    execute.add_argument("request", type=Path)
    args = parser.parse_args()
    if args.mode == "effect":
        with args.marker.open("a", encoding="utf-8") as stream:
            stream.write("APPLIED\n")
        return args.exit_code

    request = json.loads(args.request.read_text())
    store = ControlEventStore(Path(request["database"]))

    def command(context):
        if request.get("forbid_command"):
            raise AssertionError("command must not be replayed")
        observed = store.list_events(request["program_id"])
        if request.get("require_persisted_intent"):
            assert any(event["event_type"] == "TRANSITION_ATTEMPT_STARTED"
                       and event["payload"]["grant_id"] == context["grant"]["grant_id"]
                       for event in observed), "command ran before durable intent"
        process = subprocess.run([
            sys.executable, "-B", __file__, "effect", request["marker"],
            str(request.get("exit_code", 0)),
        ], check=False, timeout=30)
        if request.get("fault") == "after-side-effect":
            os._exit(18)
        result = {"status": "PASS" if process.returncode == 0 else "VALIDATION_FAILED",
                  "artifact_id": "TEST-LOCAL-PROCESS-OBSERVATION",
                  "exit_code": process.returncode}
        if process.returncode:
            result["reason_code"] = "LOCAL_PROCESS_NONZERO_EXIT"
        return result

    engine = GenericTransitionEngine(store, {"STATE": command})
    result = engine.execute_transition(
        request["program_id"], request["parent_authorization_id"],
        request["transition"], request["inputs"], created_at=request["created_at"],
        resume=request.get("resume", False),
        inject_crash_after_command=request.get("fault") == "after-observation",
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
