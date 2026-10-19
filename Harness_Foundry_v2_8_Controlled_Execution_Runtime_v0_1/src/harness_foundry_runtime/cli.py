"""`hfdriver` command-line boundary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from .engine import (
    RuntimeViolation,
    advance_one,
    advance_until_gate,
    authorization_apply,
    authorization_plan,
    authorization_revoke,
    bootstrap_apply,
    bootstrap_plan,
    plan_next,
    register_command_overlays,
    resume,
    status,
    verify_run,
)
from .migration import migration_apply, migration_plan
from .resolver import resolve_command_overlays


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hfdriver")
    commands = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("status", "Report phase, Workpack, authorization, budget, and gate"),
        ("plan-next", "Read-only computation of the unique legal transition"),
        ("verify-run", "Verify SQLite, Ledger, views, and Evidence Hashes"),
        ("advance-one", "Commit at most one authorized transition"),
        (
            "advance-until-gate",
            "Advance within one authorization until a gate or hard stop",
        ),
        ("resume", "Resume one existing Attempt without changing authority"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--execution-root", required=True)

    bootstrap_plan_parser = commands.add_parser(
        "bootstrap-plan", help="Create a bootstrap approval bundle"
    )
    bootstrap_plan_parser.add_argument(
        "--handoff",
        help="Factory handoff; omit only for an initialized migrated epoch",
    )
    bootstrap_plan_parser.add_argument("--execution-root", required=True)

    bootstrap_apply_parser = commands.add_parser(
        "bootstrap-apply", help="Consume an exact bootstrap confirmation"
    )
    bootstrap_apply_parser.add_argument("--bundle", required=True)
    _add_confirmation(bootstrap_apply_parser)

    authorization_plan_parser = commands.add_parser(
        "authorization-plan",
        help="Create an exact A3 execution authorization challenge",
    )
    authorization_plan_parser.add_argument("--execution-root", required=True)
    authorization_plan_parser.add_argument("--request", required=True)

    overlay_parser = commands.add_parser(
        "register-overlays",
        help=(
            "Validate and Hash-register resolved Command Manifests "
            "without granting execution authority"
        ),
    )
    overlay_parser.add_argument("--execution-root", required=True)
    overlay_parser.add_argument("--bundle", required=True)

    resolver_parser = commands.add_parser(
        "resolve-overlays",
        help=(
            "Resolve one provider profile across selected Workpacks and "
            "Hash-register the generated overlays"
        ),
    )
    resolver_parser.add_argument("--execution-root", required=True)
    resolver_parser.add_argument("--bundle", required=True)

    authorization_apply_parser = commands.add_parser(
        "authorization-apply",
        help="Activate a separately confirmed execution authorization",
    )
    authorization_apply_parser.add_argument("--execution-root", required=True)
    authorization_apply_parser.add_argument("--authorization", required=True)
    _add_confirmation(authorization_apply_parser)

    authorization_revoke_parser = commands.add_parser(
        "authorization-revoke",
        help="Immediately revoke an active execution authorization",
    )
    authorization_revoke_parser.add_argument("--execution-root", required=True)
    authorization_revoke_parser.add_argument(
        "--authorization-id", required=True
    )
    authorization_revoke_parser.add_argument("--reason", required=True)

    migration_plan_parser = commands.add_parser(
        "migration-plan", help="Read-only analysis of a legacy runtime"
    )
    migration_plan_parser.add_argument(
        "--legacy-candidate-root", required=True
    )
    migration_plan_parser.add_argument(
        "--legacy-execution-root", required=True
    )
    migration_plan_parser.add_argument(
        "--new-execution-root", required=True
    )
    migration_plan_parser.add_argument(
        "--copy-history-snapshot", action="store_true"
    )

    migration_apply_parser = commands.add_parser(
        "migration-apply", help="Create a new empty-epoch runtime root"
    )
    migration_apply_parser.add_argument("--plan", required=True)
    _add_confirmation(migration_apply_parser)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "status":
            result = status(args.execution_root)
        elif args.command == "plan-next":
            result = plan_next(args.execution_root)
        elif args.command == "verify-run":
            result = verify_run(args.execution_root)
        elif args.command == "bootstrap-plan":
            result = bootstrap_plan(args.handoff, args.execution_root)
        elif args.command == "bootstrap-apply":
            result = bootstrap_apply(
                args.bundle, _confirmation_text(args)
            )
        elif args.command == "authorization-plan":
            result = authorization_plan(
                args.execution_root, args.request
            )
        elif args.command == "register-overlays":
            result = register_command_overlays(
                args.execution_root, args.bundle
            )
        elif args.command == "resolve-overlays":
            result = resolve_command_overlays(
                args.execution_root, args.bundle
            )
        elif args.command == "authorization-apply":
            result = authorization_apply(
                args.execution_root,
                args.authorization,
                _confirmation_text(args),
            )
        elif args.command == "authorization-revoke":
            result = authorization_revoke(
                args.execution_root,
                args.authorization_id,
                args.reason,
            )
        elif args.command == "advance-one":
            result = advance_one(args.execution_root)
        elif args.command == "advance-until-gate":
            result = advance_until_gate(args.execution_root)
        elif args.command == "resume":
            result = resume(args.execution_root)
        elif args.command == "migration-plan":
            result = migration_plan(
                args.legacy_candidate_root,
                args.legacy_execution_root,
                args.new_execution_root,
                copy_history_snapshot=args.copy_history_snapshot,
            )
        elif args.command == "migration-apply":
            result = migration_apply(
                args.plan, _confirmation_text(args)
            )
        else:  # pragma: no cover
            raise AssertionError(args.command)
    except RuntimeViolation as exc:
        result = {
            "schema_version": "1.0",
            "status": "FAIL",
            "blocking_findings": [exc.as_finding()],
        }
        _emit(result)
        return 2
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        result = {
            "schema_version": "1.0",
            "status": "ERROR",
            "error": {
                "code": "RUNTIME_COMMAND_ERROR",
                "message": str(exc),
            },
        }
        _emit(result)
        return 1
    _emit(result)
    return (
        0
        if result.get("status")
        not in {"FAIL", "ERROR", "HARD_STOP"}
        else 3
    )


def _add_confirmation(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--confirmation-text")
    group.add_argument("--confirmation-file")


def _confirmation_text(args: argparse.Namespace) -> str:
    if args.confirmation_text is not None:
        return str(args.confirmation_text)
    return (
        Path(args.confirmation_file)
        .expanduser()
        .read_text(encoding="utf-8")
        .strip()
    )


def _emit(value: Any) -> None:
    sys.stdout.write(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
