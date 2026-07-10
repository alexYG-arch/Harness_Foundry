"""Command-line boundary used by Codex Chat and local readback tooling."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from .constants import default_runs_root, default_spec_root
from .models import (
    ChatRequest,
    FactoryError,
    RequestValidationError,
    SAFE_ID_RE,
    canonical_json,
)
from .service import FactoryService
from .store import SQLiteEventStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hffactory")
    subparsers = parser.add_subparsers(dest="command", required=True)

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
        if args.command == "verify-spec":
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
            result = _service(args, program_id=args.program_id).status(args.program_id)
        elif args.command == "readback":
            result = _service(args, program_id=args.program_id).readback(args.program_id)
        elif args.command == "verify-run":
            result = _service(args, program_id=args.program_id).verify_run(args.program_id)
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


def _service(
    args: argparse.Namespace,
    *,
    require_store: bool = True,
    program_id: str | None = None,
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
        store = SQLiteEventStore(database)
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
