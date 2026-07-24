#!/usr/bin/env python3
"""Hash-bound Codex executor and independent reviewer for one Workpack."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any


PERMISSION_PROFILE_ID = "hf_controlled"
RESERVED_ENVIRONMENT_KEYS = {
    "HF_ALLOWED_READ_ROOTS_JSON",
    "HF_ALLOWED_WRITE_ROOTS_JSON",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)


def verify_file(path: Path, expected: str, label: str) -> None:
    if not path.is_file() or sha256(path) != expected:
        raise SystemExit(f"{label}_HASH_MISMATCH:{path}")


def result_path(args: argparse.Namespace) -> Path:
    return args.evidence_root / (
        f"{safe_name(args.workpack_id)}.execution_result.json"
    )


def _root_list(
    environment_key: str, *, allow_empty: bool = False
) -> list[Path]:
    raw = os.environ.get(environment_key)
    if raw is None:
        raise SystemExit(f"{environment_key}_MISSING")
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{environment_key}_INVALID:{exc}") from exc
    if (
        not isinstance(values, list)
        or (not values and not allow_empty)
        or not all(isinstance(value, str) for value in values)
    ):
        raise SystemExit(f"{environment_key}_INVALID")
    roots = [Path(value) for value in values]
    if not all(root.is_absolute() for root in roots):
        raise SystemExit(f"{environment_key}_NOT_ABSOLUTE")
    return roots


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _runtime_python_prefix_read_roots() -> list[Path]:
    """Return only the stdlib roots of this Hash-bound interpreter."""

    roots: list[Path] = []
    for raw_prefix in (sys.base_prefix, sys.prefix):
        prefix = Path(raw_prefix)
        roots.extend((prefix, prefix.resolve()))
    return list(dict.fromkeys(root for root in roots if root.is_dir()))


@contextmanager
def _runtime_python_projection() -> Iterator[Path]:
    """Project the bound interpreter into a read-only executable root."""

    source = Path(sys.executable)
    source_hash = sha256(source)
    with tempfile.TemporaryDirectory(
        prefix="hf-runtime-python-"
    ) as temporary:
        root = Path(temporary)
        projected = root / "python3"
        shutil.copy2(source, projected)
        projected.chmod(0o555)
        if sha256(projected) != source_hash:
            raise SystemExit("RUNTIME_PYTHON_PROJECTION_HASH_MISMATCH")
        sys.stderr.write(
            "HF_RUNTIME_PYTHON_PROJECTION::"
            f"{projected}::{source_hash}\n"
        )
        yield root
        if sha256(projected) != source_hash:
            raise SystemExit("RUNTIME_PYTHON_PROJECTION_DRIFT")


def _permission_profile(
    args: argparse.Namespace,
    *,
    writable_evidence: bool,
    runtime_python_root: Path | None = None,
) -> str:
    reads = _root_list("HF_ALLOWED_READ_ROOTS_JSON")
    writes = _root_list(
        "HF_ALLOWED_WRITE_ROOTS_JSON", allow_empty=True
    )
    if not writable_evidence and writes:
        raise SystemExit("READ_ONLY_REVIEW_HAS_WRITE_ROOTS")
    access: dict[str, str] = {":minimal": "read"}
    for root in reads:
        access[str(root)] = "read"
    for root in _runtime_python_prefix_read_roots():
        access[str(root)] = "read"
    if runtime_python_root is not None:
        access[str(runtime_python_root)] = "read"
    for root in writes:
        access[str(root)] = "write"
    # Personal Codex state must never become model-readable merely because a
    # broader parent path was declared. Project-local Codex config is denied
    # as well so it cannot override this command-line permission profile.
    access[str(Path.home() / ".codex")] = "deny"
    access[str(args.workspace_root / ".codex")] = "deny"
    filesystem = ", ".join(
        f"{_toml_string(path)} = {_toml_string(mode)}"
        for path, mode in sorted(access.items())
    )
    return (
        "permissions={ "
        f"{PERMISSION_PROFILE_ID} = {{ "
        f"filesystem = {{ {filesystem} }}, "
        "network = { enabled = false } "
        "} }"
    )


def codex_command(
    args: argparse.Namespace,
    *,
    prompt: str,
    writable_evidence: bool,
    runtime_python_root: Path | None = None,
) -> tuple[list[str], str]:
    permissions = _permission_profile(
        args,
        writable_evidence=writable_evidence,
        runtime_python_root=runtime_python_root,
    )
    command = [
        str(args.codex_path),
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "-c",
        permissions,
        "-c",
        f'default_permissions="{PERMISSION_PROFILE_ID}"',
        "-c",
        'approval_policy="never"',
        "-C",
        str(args.workspace_root),
        "--skip-git-repo-check",
        "--ephemeral",
        "--color",
        "never",
    ]
    if not writable_evidence:
        command.extend(["--output-schema", str(args.review_schema)])
    command.append(prompt)
    return command, hashlib.sha256(permissions.encode("utf-8")).hexdigest()


def run_codex(
    args: argparse.Namespace,
    *,
    prompt: str,
    writable_evidence: bool,
) -> subprocess.CompletedProcess[str]:
    with _runtime_python_projection() as runtime_python_root:
        runtime_python = runtime_python_root / "python3"
        bounded_prompt = f"""
Bound Python 3.11+ executable for all Python checks in this invocation:
{runtime_python}

Use that exact executable instead of `python`, `python3`, or any interpreter
outside the authorized roots. Do not modify it.

{prompt}
""".strip()
        command, profile_hash = codex_command(
            args,
            prompt=bounded_prompt,
            writable_evidence=writable_evidence,
            runtime_python_root=runtime_python_root,
        )
        sys.stderr.write(
            "HF_CODEX_PERMISSION_PROFILE::"
            f"{PERMISSION_PROFILE_ID}::{profile_hash}\n"
        )
        environment = os.environ.copy()
        environment["HF_RUNTIME_PYTHON"] = str(runtime_python)
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=args.codex_timeout_seconds,
            env=environment,
        )
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        return completed


def _legacy_snapshot(args: argparse.Namespace) -> str:
    snapshot = (
        args.execution_root
        / "history_snapshot"
        / "legacy_execution"
    )
    if not snapshot.is_dir():
        return ""
    return f"""
An untrusted, read-only legacy execution snapshot is available at:
{snapshot}

Reuse implementation files only after revalidation. Inspect its latest
Findings and hard stop before claiming PASS. Historical PASS and authorization
do not carry into this epoch.
""".strip()


def execution_prompt(args: argparse.Namespace, *, repair: bool) -> str:
    result = result_path(args)
    action = "repair" if repair else "execute"
    finding = ""
    if repair:
        finding = (
            f"\nThe immutable Runtime Finding is {args.finding_ref} "
            f"with SHA256 {args.finding_sha256}. Read it first and repair "
            "only the reported acceptance failures."
        )
    return f"""
You are the CODEX_CODING_AGENT for a controlled Harness Foundry Workpack.

Action: {action}
Program node: {args.node_id}
Workpack: {args.workpack_id}
Workpack contract: {args.workpack_ref}
Immutable candidate root: {args.candidate_root}
Writable implementation workspace: {args.workspace_root}
Writable evidence root: {args.evidence_root}
{finding}
{_legacy_snapshot(args)}

Read the Workpack, its capsule/command manifest/index, the Program charter,
profile lock, requirement atoms, and predecessor evidence. Treat the entire
candidate root and any legacy snapshot as read-only. Implement the Workpack
completely inside the writable workspace/evidence roots. Do not install into a
real target, do not expand scope, do not use network services, and do not
claim completion without running relevant local verification.

For local artifact/evidence references, reject leading whitespace or control
characters, URI schemes, network or UNC paths, absolute paths, and parent
traversal. Resolve accepted relative references against their declared root,
verify lexical and real-path containment, and cover these cases with negative
tests whenever the Workpack exposes local references.

Before finishing, write exactly one UTF-8 JSON object to:
{result}

It must contain:
{{
  "schema_version": "1.0",
  "program_node_id": "{args.node_id}",
  "workpack_id": "{args.workpack_id}",
  "status": "PASS",
  "produced_capabilities": ["at least one capability from the contract"],
  "files_changed": ["workspace-relative paths"],
  "verification": [
    {{"command": "human-readable local check", "status": "PASS"}}
  ],
  "summary": "fact-bound implementation summary"
}}

If the contract cannot be satisfied, do not write PASS. Explain the blocker in
your final response and return a failing command outcome when possible.
""".strip()


def review_prompt(args: argparse.Namespace) -> str:
    return f"""
You are the independent, read-only reviewer for a controlled Harness Foundry
Workpack. Do not modify any file.

This invocation is the current independent review for the repaired Workpack.
Earlier failed reviews and Findings are inputs that must be revalidated here.
Do not require an already successful later review to clear an earlier review
Finding: this review is the clearing review when the current implementation,
tests, receipts, and scope all satisfy the contract.

Program node: {args.node_id}
Workpack: {args.workpack_id}
Workpack contract: {args.workpack_ref}
Immutable candidate root: {args.candidate_root}
Implementation workspace: {args.workspace_root}
Execution result: {result_path(args)}
{_legacy_snapshot(args)}

Verify the Workpack/capsule/command/index contract, produced capabilities,
changed files, local tests, negative cases, and scope boundaries. Reject
placeholders, unsupported PASS claims, missing evidence, target installation,
or access outside authorized roots. Explicitly probe local-reference handling
for leading whitespace/control characters, URI schemes, network/UNC paths,
absolute paths, parent traversal, and symlink escape when applicable. Return
only the JSON object required by the supplied output schema. Use status PASS
only when there are no findings.
""".strip()


def validate_result(args: argparse.Namespace) -> dict[str, Any]:
    path = result_path(args)
    if not path.is_file():
        raise SystemExit(f"WORKPACK_RESULT_MISSING:{path}")
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"WORKPACK_RESULT_INVALID:{exc}") from exc
    if (
        not isinstance(result, dict)
        or result.get("schema_version") != "1.0"
        or result.get("program_node_id") != args.node_id
        or result.get("workpack_id") != args.workpack_id
        or result.get("status") != "PASS"
        or not isinstance(result.get("produced_capabilities"), list)
        or not result["produced_capabilities"]
        or not isinstance(result.get("files_changed"), list)
        or not result["files_changed"]
        or not isinstance(result.get("verification"), list)
        or not result["verification"]
        or not all(
            isinstance(row, dict) and row.get("status") == "PASS"
            for row in result["verification"]
        )
    ):
        raise SystemExit("WORKPACK_RESULT_ACCEPTANCE_FAILED")
    return result


def execute(args: argparse.Namespace) -> int:
    args.workspace_root.mkdir(parents=True, exist_ok=True)
    args.evidence_root.mkdir(parents=True, exist_ok=True)
    completed = run_codex(
        args,
        prompt=execution_prompt(args, repair=False),
        writable_evidence=True,
    )
    return completed.returncode


def postflight(args: argparse.Namespace) -> int:
    result = validate_result(args)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def review(args: argparse.Namespace) -> int:
    validate_result(args)
    completed = run_codex(
        args,
        prompt=review_prompt(args),
        writable_evidence=False,
    )
    if completed.returncode != 0:
        return completed.returncode
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return 31
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if report.get("status") != "PASS" or report.get("findings"):
        return 32
    return 0


def fix(args: argparse.Namespace) -> int:
    if args.finding_ref is None or args.finding_sha256 is None:
        return 41
    verify_file(args.finding_ref, args.finding_sha256, "FINDING")
    completed = run_codex(
        args,
        prompt=execution_prompt(args, repair=True),
        writable_evidence=True,
    )
    return completed.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode", choices=("execute", "postflight", "review", "fix")
    )
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--execution-root", type=Path, required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--workpack-id", required=True)
    parser.add_argument("--workpack-ref", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--provider-sha256", required=True)
    parser.add_argument("--codex-path", type=Path, required=True)
    parser.add_argument("--codex-sha256", required=True)
    parser.add_argument("--review-schema", type=Path, required=True)
    parser.add_argument("--review-schema-sha256", required=True)
    parser.add_argument("--finding-ref", type=Path)
    parser.add_argument("--finding-sha256")
    parser.add_argument("--codex-timeout-seconds", type=int, default=1500)
    args = parser.parse_args()
    verify_file(Path(__file__), args.provider_sha256, "PROVIDER")
    verify_file(args.codex_path, args.codex_sha256, "CODEX")
    verify_file(
        args.review_schema,
        args.review_schema_sha256,
        "REVIEW_SCHEMA",
    )
    return args


def main() -> int:
    args = parse_args()
    return {
        "execute": execute,
        "postflight": postflight,
        "review": review,
        "fix": fix,
    }[args.mode](args)


if __name__ == "__main__":
    raise SystemExit(main())
