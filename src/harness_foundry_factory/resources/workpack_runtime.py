#!/usr/bin/env python3
"""Portable entrypoint for controlled Workpack hydration and execution.

The entrypoint never grants an authorization. ``execute`` requires an exact,
fresh, externally supplied A3 and delegates to the packaged provider.
"""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys


# Loading a packaged provider must not write caches into an immutable Candidate,
# including on personal-local filesystems where read-only modes are best effort.
sys.dont_write_bytecode = True
TOOLS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_ROOT))

# This entrypoint is copied beside the Candidate-internal runtime package. A
# dynamic import keeps the Factory's portable dependency scanner from treating
# that generated sibling package as a third-party Product dependency.
_runtime = importlib.import_module("harness_foundry_runtime.workpack_runtime")
RuntimeContractError = _runtime.RuntimeContractError
execute_hydrated_workpack = _runtime.execute_hydrated_workpack
hydrate_workpack_runtime = _runtime.hydrate_workpack_runtime
plan_workpack_node = _runtime.plan_workpack_node
read_json = _runtime.read_json
validate_a3_authorization = _runtime.validate_a3_authorization


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--candidate-root", type=Path, required=True)
    plan.add_argument("--node-id", required=True)
    coding = subparsers.add_parser("coding-plan", help="read a project coding task; never invoke a model")
    coding.add_argument("--candidate-root", type=Path, required=True)
    coding.add_argument("--node-id", required=True)
    coding.add_argument("--workpack-id", required=True)
    coding.add_argument("--command-id", required=True)
    coding.add_argument("--job-id")
    hydrate = subparsers.add_parser("hydrate")
    hydrate.add_argument("--candidate-root", type=Path, required=True)
    hydrate.add_argument("--execution-root", type=Path, required=True)
    hydrate.add_argument("--overlay", type=Path, required=True)
    validate = subparsers.add_parser("validate-a3")
    validate.add_argument("--hydration", type=Path, required=True)
    validate.add_argument("--authorization", type=Path, required=True)
    execute = subparsers.add_parser("execute")
    execute.add_argument("--candidate-root", type=Path, required=True)
    execute.add_argument("--execution-root", type=Path, required=True)
    execute.add_argument("--hydration", type=Path, required=True)
    execute.add_argument("--authorization", type=Path, required=True)
    execute.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            result = plan_workpack_node(args.candidate_root, args.node_id)
        elif args.command == "coding-plan":
            protocol = importlib.import_module("harness_foundry_runtime.coding_protocol")
            result = protocol.plan_coding_command(args.candidate_root, args.node_id, args.workpack_id,
                                                  args.command_id, job_id=args.job_id)
        elif args.command == "hydrate":
            result = hydrate_workpack_runtime(
                args.candidate_root,
                args.execution_root,
                read_json(args.overlay, "COMMAND_OVERLAY_INVALID"),
            )
        elif args.command == "validate-a3":
            hydration = read_json(args.hydration, "RUNTIME_HYDRATION_INVALID")
            result = {
                "status": "PASS",
                "authorization": validate_a3_authorization(
                    hydration,
                    read_json(args.authorization, "A3_AUTHORIZATION_INVALID"),
                ),
                "authorization_consumed": False,
                "workpack_executed": False,
            }
        else:
            result = execute_hydrated_workpack(
                args.candidate_root,
                args.execution_root,
                read_json(args.hydration, "RUNTIME_HYDRATION_INVALID"),
                read_json(args.authorization, "A3_AUTHORIZATION_INVALID"),
                timeout_seconds=args.timeout_seconds,
            )
    except RuntimeContractError as exc:
        print(
            json.dumps(
                {"status": "FAIL", "code": exc.code, "message": exc.message},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    # A completed provider call can still report a failed Workpack. Propagate
    # that outcome to the caller instead of treating JSON serialization as PASS.
    return 0 if result.get("status") in {
        "PASS", "READY_FOR_A3_PREPARATION", "DECLARED_WORKPACK_PLAN", "DECLARED_CODING_TASK",
    } else 1


if __name__ == "__main__":
    sys.exit(main())
