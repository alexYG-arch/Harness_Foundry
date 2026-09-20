"""Public generic CLI: no Candidate, legacy kernel, sibling spec or domain pipeline."""

import argparse
import json
from pathlib import Path
import sys

from .build_types import FactoryError, RequestValidationError, canonical_json
from .identity import BASELINE_FACTORY_ID, FACTORY_ID, FACTORY_VERSION, TARGET_PROTOCOL_VERSION


BUILD_COMMANDS = frozenset({
    "compile-build-plan", "record-build-plan", "capture-build-sources",
    "prepare-build-authorization", "approve-build-authorization", "revoke-build-authorization",
    "resolve-build-attempt", "advance-build", "read-build", "read-history",
})


def _load_request(location):
    value = json.load(sys.stdin) if location == "-" else json.loads(Path(location).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RequestValidationError("request JSON must contain one object")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(prog="hffactory")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("version", *sorted(BUILD_COMMANDS)):
        command = commands.add_parser(name)
        command.add_argument("--json", action="store_true")
        if name in {"read-build", "read-history"}:
            command.add_argument("--program-id", required=True)
        elif name != "version":
            command.add_argument("--request", required=True)
        if name == "read-history":
            command.add_argument("--database", required=True)
        elif name not in {"version", "compile-build-plan"}:
            command.add_argument("--control-db", required=True)
    args = parser.parse_args(argv)
    code = 0
    try:
        if args.command == "version":
            result = {"schema_version": "1.0", "status": "PASS", "factory_id": FACTORY_ID,
                      "implementation_version": FACTORY_VERSION, "target_protocol_version": TARGET_PROTOCOL_VERSION,
                      "baseline_factory_id": BASELINE_FACTORY_ID,
                      "product_route": "GENERIC_REVIEWED_BUILD", "storage_format": "REVISION_V1",
                      "legacy_specification_required": False, "writes_performed": False}
        elif args.command == "compile-build-plan":
            from .build_plan import compile_build_plan, validate_compiled_build_plan
            request = _load_request(args.request)
            if set(request) != {"requirement_ir", "plan"}:
                raise RequestValidationError("compile-build-plan requires exactly requirement_ir and plan")
            result = compile_build_plan(request["requirement_ir"], request["plan"])
            validate_compiled_build_plan(request["requirement_ir"], request["plan"], result)
        elif args.command == "read-history":
            from .legacy_history import read_history
            result = read_history(args.database, args.program_id)
        elif args.command == "read-build":
            from .build_entrypoint import read_build
            result = read_build(args.control_db, args.program_id)
        else:
            from .build_entrypoint import apply_build_request
            result = apply_build_request(args.command, _load_request(args.request), args.control_db)
        if args.command == "advance-build" and result.get("status") != "PLAN_CHECKS_ACCEPTED":
            code = 6
    except FactoryError as exc:
        result, code = exc.as_response(), exc.exit_code
    except (OSError, ValueError) as exc:
        error = RequestValidationError("failed to read or validate request", details={"error": str(exc)})
        result, code = error.as_response(), error.exit_code
    except Exception as exc:
        result, code = {"schema_version": "1.0", "status": "ERROR",
                        "error": {"code": "INTERNAL_FACTORY_ERROR", "message": str(exc)}}, 1
    print(canonical_json(result) if args.json else json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
