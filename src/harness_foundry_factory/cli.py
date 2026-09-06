"""Command-line boundary used by Codex Chat and local readback tooling."""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

from .constants import (
    BASELINE_FACTORY_ID,
    FACTORY_ID,
    FACTORY_VERSION,
    HF28_PACKAGE_ID,
    HF28_SCHEMA_VERSION,
    TARGET_PROTOCOL_VERSION,
    default_runs_root,
    default_spec_root,
)
from .models import (
    ChatRequest,
    FactoryError,
    RequestValidationError,
    SAFE_ID_RE,
    canonical_json,
)
from .service import FactoryService
from .store import ControlEventStore, SQLiteEventStore
from .control_kernel import ControlKernelError, GenericTransitionEngine
from .core_validation import (
    CoreValidationError,
    project_core_evidence,
    validate_core,
)
from .portable import (
    PortablePackageError,
    package_local,
    self_check_diagnostic,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hffactory")
    subparsers = parser.add_subparsers(dest="command", required=True)

    version = subparsers.add_parser("version", help="Show v2.9 product identity")
    _add_json_flag(version)

    verify_spec = subparsers.add_parser("verify-spec", help="Verify the pinned v2.8 spec")
    _add_common_paths(verify_spec, database=False)
    _add_json_flag(verify_spec)

    chat_turn = subparsers.add_parser("chat-turn", help="Apply one strict JSON chat request")
    chat_turn.add_argument("request_path", nargs="?", help="JSON request file or '-' for stdin")
    chat_turn.add_argument("--request", "--request-file", dest="request_file")
    _add_common_paths(chat_turn, database=True)
    _add_json_flag(chat_turn)

    status = subparsers.add_parser("status", help="Read current Program status")
    status.add_argument("--program-id", required=True)
    _add_common_paths(status, database=True)
    _add_json_flag(status)

    readback = subparsers.add_parser("readback", help="Read complete authoring state")
    readback.add_argument("--program-id", required=True)
    _add_common_paths(readback, database=True)
    _add_json_flag(readback)

    handoff = subparsers.add_parser(
        "prepare-execution-handoff",
        help="Read audited Candidate approval for a separate runtime; grants no execution authority",
    )
    handoff.add_argument("--program-id", required=True)
    _add_common_paths(handoff, database=True)
    _add_json_flag(handoff)

    requirement_readback = subparsers.add_parser(
        "requirement-readback",
        help="Read the frozen Requirement and its human-approved lock",
    )
    requirement_readback.add_argument("--program-id", required=True)
    _add_common_paths(requirement_readback, database=True)
    _add_json_flag(requirement_readback)

    architecture_readback = subparsers.add_parser(
        "architecture-readback",
        help="Read the production Architecture and lock status",
    )
    architecture_readback.add_argument("--program-id", required=True)
    _add_common_paths(architecture_readback, database=True)
    _add_json_flag(architecture_readback)

    compile_contract = subparsers.add_parser(
        "compile",
        help="Compile the confirmed Requirement and Architecture locks to stdout",
    )
    compile_contract.add_argument("--program-id", required=True)
    _add_common_paths(compile_contract, database=True)
    _add_json_flag(compile_contract)

    advance_authoring = subparsers.add_parser(
        "advance-authoring-until-gate",
        help="Advance internal Authoring checks to the next real human gate",
    )
    advance_authoring.add_argument("--program-id", required=True)
    _add_common_paths(advance_authoring, database=True)
    _add_json_flag(advance_authoring)

    runtime_advance = subparsers.add_parser(
        "advance-until-gate",
        help="Advance Runtime transitions within an approved Parent authorization",
    )
    runtime_advance.add_argument("--request", required=True)
    runtime_advance.add_argument("--control-db", required=True)
    _add_json_flag(runtime_advance)

    checkpoint = subparsers.add_parser(
        "checkpoint", help="Append a durable Runtime Checkpoint and Resume Capsule"
    )
    checkpoint.add_argument("--request", required=True)
    checkpoint.add_argument("--control-db", required=True)
    _add_json_flag(checkpoint)

    resume = subparsers.add_parser(
        "resume", help="Resume one transition from a durable Resume Capsule"
    )
    resume.add_argument("--request", required=True)
    resume.add_argument("--control-db", required=True)
    _add_json_flag(resume)

    explain_stop = subparsers.add_parser(
        "explain-stop", help="Explain the latest Runtime stop without writing"
    )
    explain_stop.add_argument("--program-id", required=True)
    explain_stop.add_argument("--control-db", required=True)
    _add_json_flag(explain_stop)

    package = subparsers.add_parser(
        "package-local",
        help="Preflight or create a portable local v2.9 product package",
    )
    package.add_argument("--output-root")
    _add_json_flag(package)

    self_check = subparsers.add_parser(
        "self-check-diagnostic",
        help="Run a non-authoritative diagnostic portable package check",
    )
    self_check.add_argument("--package-root", required=True)
    _add_json_flag(self_check)

    validate_core_parser = subparsers.add_parser(
        "validate-core",
        help="Run the read-only official core behavior validator",
    )
    _add_json_flag(validate_core_parser)

    project_core = subparsers.add_parser(
        "project-core-evidence",
        help="Project deterministic non-authoritative core implementation evidence",
    )
    _add_json_flag(project_core)

    verify_run = subparsers.add_parser("verify-run", help="Verify state and event hash chains")
    verify_run.add_argument("--program-id", required=True)
    _add_common_paths(verify_run, database=True)
    _add_json_flag(verify_run)

    validate = subparsers.add_parser("validate-candidate", help="Validate a generated candidate")
    validate.add_argument("candidate_path", nargs="?")
    validate.add_argument("--candidate-root")
    validate.add_argument("--program-id")
    _add_common_paths(validate, database=True)
    _add_json_flag(validate)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "version":
            result = _version_result()
        elif args.command == "verify-spec":
            service = _service(args, require_store=False)
            result = service.verify_spec()
        elif args.command == "chat-turn":
            request_location = args.request_file or args.request_path
            if not request_location:
                raise RequestValidationError(
                    "chat-turn requires a JSON request file or '-' for stdin"
                )
            request = ChatRequest.from_dict(_load_request(request_location))
            result = _service(args, program_id=request.program_id).handle_chat_turn(request)
        elif args.command == "status":
            result = _service(args, program_id=args.program_id, read_only_store=True).status(args.program_id)
        elif args.command == "readback":
            result = _service(args, program_id=args.program_id, read_only_store=True).readback(args.program_id)
        elif args.command == "prepare-execution-handoff":
            result = _service(
                args, program_id=args.program_id, read_only_store=True,
            ).prepare_execution_handoff(args.program_id)
        elif args.command == "requirement-readback":
            result = _service(
                args,
                program_id=args.program_id,
                read_only_store=True,
            ).requirement_readback(args.program_id)
        elif args.command == "architecture-readback":
            result = _service(
                args,
                program_id=args.program_id,
                read_only_store=True,
            ).architecture_readback(args.program_id)
        elif args.command == "compile":
            result = _service(
                args,
                program_id=args.program_id,
                read_only_store=True,
            ).compile_contract(args.program_id)
        elif args.command == "advance-authoring-until-gate":
            result = _service(
                args,
                program_id=args.program_id,
            ).advance_authoring_until_gate(args.program_id)
        elif args.command == "advance-until-gate":
            result = _runtime_advance(args)
        elif args.command == "checkpoint":
            result = _runtime_checkpoint(args)
        elif args.command == "resume":
            result = _runtime_resume(args)
        elif args.command == "explain-stop":
            _validate_runtime_program_id(args.program_id)
            store = ControlEventStore(
                Path(args.control_db).expanduser().resolve(), read_only=True
            )
            result = GenericTransitionEngine(store, {}).explain_stop(
                args.program_id
            )
        elif args.command == "package-local":
            result = package_local(args.output_root)
        elif args.command == "self-check-diagnostic":
            result = self_check_diagnostic(args.package_root)
        elif args.command == "validate-core":
            result = validate_core()
        elif args.command == "project-core-evidence":
            result = project_core_evidence()
        elif args.command == "verify-run":
            result = _service(
                args,
                program_id=args.program_id,
                read_only_store=True,
            ).verify_run(args.program_id)
        elif args.command == "validate-candidate":
            service = _service(
                args,
                require_store=bool(args.program_id),
                program_id=args.program_id,
            )
            candidate_path = args.candidate_root or args.candidate_path
            if args.program_id:
                if candidate_path:
                    raise RequestValidationError(
                        "use either --program-id or a candidate path, not both"
                    )
                result = service.validate_program_candidate(args.program_id)
            else:
                if not candidate_path:
                    raise RequestValidationError(
                        "validate-candidate requires a path or --program-id"
                    )
                result = service.validate_candidate(candidate_path)
        else:  # pragma: no cover - argparse enforces the closed command set
            parser.error(f"unknown command: {args.command}")
            return 2
    except FactoryError as exc:
        _emit(exc.as_response(), json_output=getattr(args, "json", False))
        return exc.exit_code
    except ControlKernelError as exc:
        _emit(
            {
                "schema_version": "2.9",
                "status": "ERROR",
                "error": {
                    "code": "RUNTIME_CONTROL_GATE_BLOCKED",
                    "reason_code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                },
            },
            json_output=getattr(args, "json", False),
        )
        return 6
    except PortablePackageError as exc:
        _emit(
            {
                "schema_version": "2.9",
                "status": "ERROR",
                "error": {
                    "code": "PORTABLE_PACKAGE_GATE_BLOCKED",
                    "reason_code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                },
                "writes_performed": False,
                "security_authority": False,
                "certification_claimed": False,
            },
            json_output=getattr(args, "json", False),
        )
        return 6
    except CoreValidationError as exc:
        _emit(
            {
                "schema_version": "2.9",
                "status": "ERROR",
                "error": {
                    "code": "CORE_VALIDATION_GATE_BLOCKED",
                    "reason_code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                },
                "writes_performed": False,
                "external_certification_claimed": False,
                "release_receipt_created": False,
            },
            json_output=getattr(args, "json", False),
        )
        return 6
    except (OSError, json.JSONDecodeError) as exc:
        error = RequestValidationError(
            "failed to read JSON request", details={"error": str(exc)}
        )
        _emit(error.as_response(), json_output=getattr(args, "json", False))
        return error.exit_code
    except Exception as exc:  # defensive CLI boundary; no traceback on stdout
        result = {
            "schema_version": "1.0",
            "status": "ERROR",
            "error": {"code": "INTERNAL_FACTORY_ERROR", "message": str(exc)},
        }
        _emit(result, json_output=getattr(args, "json", False))
        return 1

    _emit(result, json_output=getattr(args, "json", False))
    if isinstance(result, dict) and result.get("status") == "FAIL":
        return 7 if args.command == "validate-candidate" else 6
    return 0


def _version_result() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "PASS",
        "factory_id": FACTORY_ID,
        "target_protocol_version": TARGET_PROTOCOL_VERSION,
        "implementation_version": FACTORY_VERSION,
        "baseline_factory_id": BASELINE_FACTORY_ID,
        "baseline_specification": {
            "package_id": HF28_PACKAGE_ID,
            "schema_version": HF28_SCHEMA_VERSION,
        },
        "human_summary": (
            f"{FACTORY_ID} target={TARGET_PROTOCOL_VERSION} "
            f"implementation={FACTORY_VERSION}"
        ),
    }


def _runtime_advance(args: argparse.Namespace) -> dict[str, Any]:
    request = _load_request(args.request)
    _require_test_adapter_mode(request)
    program_id = request.get("program_id")
    if not isinstance(program_id, str) or not SAFE_ID_RE.fullmatch(program_id):
        raise RequestValidationError("Runtime program_id must be path-safe")
    contracts = request.get("contracts")
    inputs = request.get("inputs_by_transition")
    bindings = request.get("expected_bindings")
    adapter_results = request.get("test_adapter_results")
    if not all(isinstance(value, dict) for value in (contracts, inputs, bindings, adapter_results)):
        raise RequestValidationError(
            "Runtime request requires contracts, inputs, bindings and adapter results"
        )
    queues: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
    for command_class, results in adapter_results.items():
        if not isinstance(command_class, str) or not isinstance(results, list):
            raise RequestValidationError("test_adapter_results is invalid")
        for result in results:
            if not isinstance(result, dict):
                raise RequestValidationError("test adapter result must be an object")
            queues[command_class].append(dict(result))

    def adapter(command_class: str):
        def invoke(context: dict[str, Any]) -> dict[str, Any]:
            queue = queues[command_class]
            if not queue:
                raise ControlKernelError(
                    "TEST_ADAPTER_RESULT_EXHAUSTED", command_class
                )
            return dict(queue.popleft())

        return invoke

    store = ControlEventStore(Path(args.control_db).expanduser().resolve())
    engine = GenericTransitionEngine(
        store,
        {command_class: adapter(command_class) for command_class in queues},
    )
    return engine.runtime_advance_until_gate(
        program_id,
        str(request.get("parent_authorization_id")),
        contracts,
        inputs,
        start_transition_id=str(request.get("start_transition_id")),
        created_at=str(request.get("created_at")),
        max_transitions=request.get("max_transitions"),
        expected_bindings=bindings,
        expected_control_state_sha256=str(
            request.get("expected_control_state_sha256")
        ),
        environment_manifest=request.get("environment_manifest"),
        artifact_manifest=request.get("artifact_manifest"),
    )


def _runtime_checkpoint(args: argparse.Namespace) -> dict[str, Any]:
    request = _load_request(args.request)
    program_id = _required_string(request, "program_id")
    _validate_runtime_program_id(program_id)
    store = ControlEventStore(Path(args.control_db).expanduser().resolve())
    return GenericTransitionEngine(store, {}).create_checkpoint(
        program_id,
        _required_string(request, "parent_authorization_id"),
        expected_bindings=_required_mapping(request, "expected_bindings"),
        expected_control_state_sha256=str(
            request.get("expected_control_state_sha256")
        ),
        environment_manifest=_required_mapping(
            request, "environment_manifest"
        ),
        artifact_manifest=_required_mapping(request, "artifact_manifest"),
        resume_node=_required_string(request, "resume_node"),
        created_at=_required_string(request, "created_at"),
    )


def _runtime_resume(args: argparse.Namespace) -> dict[str, Any]:
    request = _load_request(args.request)
    _require_test_adapter_mode(request)
    capsule = _required_mapping(request, "resume_capsule")
    _validate_runtime_program_id(_required_string(capsule, "program_id"))
    transition = _required_mapping(request, "transition")
    command = transition.get("command_contract")
    command_class = (
        command.get("command_class") if isinstance(command, Mapping) else None
    )
    results = request.get("test_adapter_results")
    if not isinstance(command_class, str) or not isinstance(results, list):
        raise RequestValidationError(
            "Resume requires one transition command and test adapter result list"
        )
    queue = deque(
        dict(result) for result in results if isinstance(result, Mapping)
    )
    if len(queue) != len(results):
        raise RequestValidationError("test adapter result must be an object")

    def adapter(context: dict[str, Any]) -> dict[str, Any]:
        if not queue:
            raise ControlKernelError(
                "TEST_ADAPTER_RESULT_EXHAUSTED", command_class
            )
        return dict(queue.popleft())

    store = ControlEventStore(Path(args.control_db).expanduser().resolve())
    engine = GenericTransitionEngine(store, {command_class: adapter})
    fencing_token = request.get("expected_fencing_token")
    return engine.resume_from_capsule(
        capsule,
        transition,
        _required_mapping(request, "inputs"),
        expected_bindings=_required_mapping(request, "expected_bindings"),
        expected_control_state_sha256=str(
            request.get("expected_control_state_sha256")
        ),
        expected_fencing_token=fencing_token,
        environment_manifest=_required_mapping(
            request, "environment_manifest"
        ),
        artifact_manifest=_required_mapping(request, "artifact_manifest"),
        created_at=_required_string(request, "created_at"),
    )


def _require_test_adapter_mode(request: Mapping[str, Any]) -> None:
    if request.get("adapter_mode") != "TEST_ONLY_IDEMPOTENT_ADAPTERS":
        raise ControlKernelError(
            "PRODUCTION_COMMAND_ADAPTERS_NOT_CONFIGURED",
            "This implementation slice exposes only explicitly enabled test adapters",
        )
    if os.environ.get("HFFACTORY_ALLOW_TEST_ADAPTERS") != "1":
        raise ControlKernelError(
            "TEST_ADAPTER_MODE_DISABLED",
            "Test-only Runtime adapters require an explicit environment opt-in",
        )


def _required_mapping(
    request: Mapping[str, Any], field: str
) -> dict[str, Any]:
    value = request.get(field)
    if not isinstance(value, Mapping):
        raise RequestValidationError(f"{field} must be an object")
    return dict(value)


def _required_string(request: Mapping[str, Any], field: str) -> str:
    value = request.get(field)
    if not isinstance(value, str) or not value:
        raise RequestValidationError(f"{field} must be a non-empty string")
    return value


def _validate_runtime_program_id(program_id: str) -> None:
    if not SAFE_ID_RE.fullmatch(program_id) or ".." in program_id:
        raise RequestValidationError(
            "Runtime program_id must be a path-safe identifier"
        )


def _service(
    args: argparse.Namespace,
    *,
    require_store: bool = True,
    program_id: str | None = None,
    read_only_store: bool = False,
) -> FactoryService:
    runs_root = Path(args.runs_root).expanduser().resolve()
    if program_id is not None and (
        not SAFE_ID_RE.fullmatch(program_id) or ".." in program_id
    ):
        raise RequestValidationError("program_id must be a path-safe identifier")
    store: SQLiteEventStore | None
    if require_store:
        if args.db:
            database = Path(args.db).expanduser().resolve()
        elif program_id:
            database = runs_root / program_id / "factory.sqlite3"
        else:
            raise RequestValidationError(
                "program_id is required to select the run database"
            )
        store = SQLiteEventStore(database, read_only=read_only_store)
    else:
        store = None
    return FactoryService(
        store,  # type: ignore[arg-type] -- read-only commands do not access the store
        spec_root=Path(args.spec_root).expanduser().resolve(),
        runs_root=runs_root,
    )


def _load_request(location: str) -> dict[str, Any]:
    if location == "-":
        value = json.load(sys.stdin)
    else:
        value = json.loads(Path(location).expanduser().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RequestValidationError("request JSON must contain one object")
    return value


def _emit(value: Any, *, json_output: bool) -> None:
    if json_output:
        sys.stdout.write(canonical_json(value) + "\n")
        return
    if isinstance(value, dict):
        summary = value.get("human_summary")
        if summary:
            sys.stdout.write(str(summary) + "\n")
            return
    sys.stdout.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _add_common_paths(parser: argparse.ArgumentParser, *, database: bool) -> None:
    parser.add_argument("--spec-root", default=str(default_spec_root()))
    parser.add_argument("--runs-root", default=str(default_runs_root()))
    if database:
        parser.add_argument("--db")


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Emit one JSON object on stdout")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
