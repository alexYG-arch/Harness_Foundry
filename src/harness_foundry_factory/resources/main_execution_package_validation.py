#!/usr/bin/env python3
"""Portable entrypoint for structural Main Execution Package validation."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys


TOOLS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_ROOT))

_runtime = importlib.import_module(
    "harness_foundry_runtime.main_execution_package_validation"
)
ContractError = _runtime.ContractError
execute_action = _runtime.execute_action
validate_static_contract = _runtime.validate_static_contract


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-contract")
    validate.add_argument("--candidate-root", type=Path, required=True)
    execute = subparsers.add_parser("execute")
    execute.add_argument("--candidate-root", type=Path, required=True)
    execute.add_argument("--execution-root", type=Path, required=True)
    execute.add_argument("--command-manifest", type=Path, required=True)
    execute.add_argument("--authorization", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-contract":
            contract = validate_static_contract(args.candidate_root.resolve())
            result = {
                "status": "PASS",
                "action_id": contract["action_id"],
                "executor_implementation_sha256": contract[
                    "executor_implementation_sha256"
                ],
                "result_schema_sha256": contract["result_schema_sha256"],
            }
        else:
            result = execute_action(
                args.candidate_root,
                args.execution_root,
                args.command_manifest,
                args.authorization,
            )
    except ContractError as exc:
        print(
            json.dumps(
                {"status": "FAIL", "code": exc.code, "message": exc.message},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
