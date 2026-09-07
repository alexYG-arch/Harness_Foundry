"""Candidate-derived Workpack plans and controlled materialization provider.

The Factory packages this module into a Candidate, but never invokes its
side-effecting entrypoint.  A separately authorized Execution Runtime may use
it to hydrate the planned command manifest, validate an exact one-shot A3, and
execute the structural package Workpack inside two declared write roots.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence


NODE_ID = "MAIN_EXECUTION_PACKAGE_MATERIALIZED"
# Legacy constants remain for compatibility; live Workpack identity and
# predecessor selection below come from the Candidate DAG and its own index.
WORKPACK_ID = "WP-HARNESS-FOUNDRY-V2-9-CHAT-FACTORY-G0-001"
AUTHORIZATION_CLASS = "A3_PROGRAM_BOUNDED"
ASSURANCE_PROFILE = "SELF_USE_LOCAL_TRUSTED_OPERATOR"
VALIDATION_SCOPE = "STRUCTURAL_PACKAGE_CONTRACT_ONLY"
PROVIDER_IMPLEMENTATION_REF = (
    "tools/harness_foundry_runtime/workpack_runtime.py"
)
RUNTIME_ENTRYPOINT_REF = "tools/workpack_runtime.py"
RUNTIME_CONTRACT_REF = "validation/CONTROLLED_WORKPACK_RUNTIME_CONTRACT.json"
COMMAND_MANIFEST_REF = (
    "commands/WP-HARNESS-FOUNDRY-V2-9-CHAT-FACTORY-G0-001.commands.json"
)
CAPSULE_REF = (
    "capsules/WP-HARNESS-FOUNDRY-V2-9-CHAT-FACTORY-G0-001.capsule.json"
)
WORKPACK_INDEX_REF = "WORKPACK_INDEX.json"
DAG_REF = "ENGINEERING_PROJECT_DAG.json"
PORTABLE_MANIFEST_REF = "validation/PORTABLE_FILE_MANIFEST.json"
PREDECESSOR_RESULT_REF = (
    "evidence/engineering_dag/PROGRAM_DRIVER_RUNTIME_VERIFIED/result.json"
)
CONTROL_STATE_REF = ".harness-foundry/control/PROGRAM_CONTROL_STATE.json"
CONTROL_EVENTS_REF = ".harness-foundry/control/PROGRAM_CONTROL_EVENTS.jsonl"
REPOSITORY_REF = "project_start_packages/main_build/repository"
NODE_EVIDENCE_REF = "evidence/engineering_dag/MAIN_EXECUTION_PACKAGE_MATERIALIZED"
RESULT_REF = f"{NODE_EVIDENCE_REF}/result.json"
COMMAND_IDS = ("ROOT-CODEX-CODING", "ROOT-MATERIALIZATION-VERIFY")
MAX_TRANSITIONS = 1
MAX_LOOP_ROUNDS = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_CODEX_FLAGS = {
    "--dangerously-bypass-approvals-and-sandbox",
    "--sandbox=danger-full-access",
}


class RuntimeContractError(RuntimeError):
    """Stable fail-closed error raised before an undeclared side effect."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def json_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def hash_without(value: Mapping[str, Any], field: str) -> str:
    return json_hash({key: item for key, item in value.items() if key != field})


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise RuntimeContractError("RUNTIME_INPUT_MISSING", str(path)) from exc
    return digest.hexdigest()


def read_json(path: Path, code: str = "RUNTIME_INPUT_INVALID") -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeContractError(code, f"{path.name}: {exc}") from None
    if not isinstance(value, dict):
        raise RuntimeContractError(code, f"{path.name} must contain an object")
    return value


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise RuntimeContractError(code, message)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _resolved_roots(
    candidate_root: Path, execution_root: Path
) -> tuple[Path, Path]:
    _require(
        not candidate_root.is_symlink() and not execution_root.is_symlink(),
        "RUNTIME_ROOT_CONTAINMENT_INVALID",
        "Candidate and Execution Root symlinks are forbidden",
    )
    candidate = candidate_root.resolve()
    execution = execution_root.resolve()
    _require(candidate.is_dir(), "RUNTIME_INPUT_MISSING", "Candidate is missing")
    _require(execution.is_dir(), "RUNTIME_INPUT_MISSING", "Execution Root is missing")
    _require(
        candidate != execution
        and candidate not in execution.parents
        and execution not in candidate.parents,
        "RUNTIME_ROOT_CONTAINMENT_INVALID",
        "Candidate and Execution Root must be disjoint",
    )
    return candidate, execution


def _contained(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def candidate_identity(candidate_root: Path) -> str:
    manifest = read_json(
        candidate_root / PORTABLE_MANIFEST_REF,
        "CANDIDATE_PORTABLE_MANIFEST_INVALID",
    )
    files = manifest.get("files")
    excluded = manifest.get("excluded_files")
    _require(
        isinstance(files, dict) and bool(files),
        "CANDIDATE_PORTABLE_MANIFEST_INVALID",
        "portable file inventory is missing",
    )
    _require(
        isinstance(excluded, list),
        "CANDIDATE_PORTABLE_MANIFEST_INVALID",
        "excluded file inventory is missing",
    )
    actual: set[str] = set()
    for path in candidate_root.rglob("*"):
        _require(
            not path.is_symlink(),
            "CANDIDATE_PORTABLE_MANIFEST_INVALID",
            f"symlink is forbidden: {path.relative_to(candidate_root)}",
        )
        if path.is_file():
            relative = path.relative_to(candidate_root).as_posix()
            if relative not in excluded:
                actual.add(relative)
    _require(
        actual == set(files),
        "CANDIDATE_PORTABLE_MANIFEST_INVALID",
        "portable inventory differs from Candidate bytes",
    )
    for relative, expected in files.items():
        relative_path = Path(str(relative))
        path = candidate_root / relative_path
        _require(
            not relative_path.is_absolute()
            and ".." not in relative_path.parts
            and path.is_file()
            and _is_sha256(expected)
            and file_hash(path) == expected,
            "CANDIDATE_PORTABLE_MANIFEST_INVALID",
            str(relative),
        )
    return json_hash(files)


def _manifest_file_hash(candidate_root: Path, relative: str) -> str:
    portable = read_json(candidate_root / PORTABLE_MANIFEST_REF)
    files = portable.get("files")
    expected = files.get(relative) if isinstance(files, Mapping) else None
    actual = file_hash(candidate_root / relative)
    _require(
        _is_sha256(expected) and expected == actual,
        "CANDIDATE_RUNTIME_BINDING_INVALID",
        f"portable Hash binding failed: {relative}",
    )
    return actual


def _candidate_ref(base: Path, ref: Any) -> str:
    _require(isinstance(ref, str) and bool(ref), "WORKPACK_PLAN_INVALID", "missing Candidate ref")
    path = Path(ref)
    _require(not path.is_absolute() and ".." not in path.parts and "://" not in ref,
             "WORKPACK_PLAN_INVALID", "Workpack refs must remain relative to their Candidate package")
    return (base / path).as_posix()


def _load_workpack_plan(candidate_root: Path, node_id: str) -> dict[str, Any]:
    """Resolve root and project Workpacks through their declared DAG ownership.

    Keep the complete unit and command contracts, including per-Job leases and
    task bundles. Resolution is not hydration, acceptance or execution authority.
    """
    source_refs = {DAG_REF}

    def load(ref: str) -> dict[str, Any]:
        source_refs.add(ref)
        _manifest_file_hash(candidate_root, ref)
        return read_json(candidate_root / ref, "WORKPACK_PLAN_INVALID")

    dag = load(DAG_REF)
    nodes = [item for item in dag.get("nodes", [])
             if isinstance(item, Mapping) and item.get("node_id") == node_id]
    _require(len(nodes) == 1, "WORKPACK_PLAN_INVALID", "DAG node must resolve uniquely")
    node = nodes[0]
    sequence = node.get("project_workpack_sequence") or (
        [node["workpack_id"]] if node.get("workpack_id") else []
    )
    _require(isinstance(sequence, list) and bool(sequence)
             and all(isinstance(item, str) for item in sequence)
             and len(sequence) == len(set(sequence)),
             "WORKPACK_PLAN_INVALID", "node has no unique ordered Workpack set")
    index_ref = _candidate_ref(Path(), node.get("project_workpack_index_ref"))
    base = Path(index_ref).parent
    index = load(index_ref)
    _require(index.get("project_id", node.get("project_id")) == node.get("project_id"),
             "WORKPACK_PLAN_INVALID", "index belongs to another project")
    units = []
    for workpack_id in sequence:
        matches = [item for item in index.get("workpacks", [])
                   if isinstance(item, Mapping) and item.get("workpack_id") == workpack_id]
        _require(len(matches) == 1, "WORKPACK_PLAN_INVALID", f"ambiguous or missing Workpack: {workpack_id}")
        workpack = matches[0]
        _require(workpack.get("status") == "PLANNED_NOT_ACTIVE"
                 and workpack.get("execution_authorization_ref") is None
                 and workpack.get("auto_start") is False
                 and workpack.get("project_id", index.get("project_id")) == node.get("project_id")
                 and workpack.get("program_control_node_id", node_id) == node_id,
                 "WORKPACK_PLAN_INVALID", f"Workpack is active or belongs to another node/project: {workpack_id}")
        command_ref = _candidate_ref(base, workpack.get("command_manifest_ref"))
        capsule_ref = _candidate_ref(base, workpack.get("capsule_ref"))
        manifest, capsule = load(command_ref), load(capsule_ref)
        commands = manifest.get("commands")
        order = workpack.get("command_execution_order")
        _require(isinstance(commands, list) and all(isinstance(item, Mapping) for item in commands)
                 and isinstance(order, list) and bool(order)
                 and all(isinstance(item, str) for item in order)
                 and len(order) == len(set(order))
                 and len(commands) == len(order)
                 and {item.get("command_id") for item in commands} == set(order)
                 and workpack.get("command_ids") == order
                 and manifest.get("workpack_id") == workpack_id
                 and manifest.get("program_id") == index.get("program_id")
                 and manifest.get("execution_started") is False
                 and capsule.get("workpack_id") == workpack_id
                 and capsule.get("program_id") == index.get("program_id")
                 and capsule.get("project_id", node.get("project_id")) == node.get("project_id")
                 and capsule.get("execution_authorization_ref") is None
                 and capsule.get("hydration_complete") is False
                 and capsule.get("execution_authorized", False) is False,
                 "WORKPACK_PLAN_INVALID", f"Workpack commands or capsule differ from index: {workpack_id}")
        command_by_id = {item["command_id"]: item for item in commands}
        task_ref = workpack.get("task_bundle_ref")
        task_ref = _candidate_ref(base, task_ref) if task_ref else None
        task_bundle = load(task_ref) if task_ref else None
        if task_bundle is not None:
            _require(task_bundle.get("workpack_id") == workpack_id
                     and task_bundle.get("project_id") == node.get("project_id")
                     and task_bundle.get("program_id") == index.get("program_id"),
                     "WORKPACK_PLAN_INVALID", "task bundle belongs to another Workpack/project/Program")
        units.append({
            "workpack_id": workpack_id, "project_id": node.get("project_id"),
            "workpack": dict(workpack), "command_manifest_ref": command_ref,
            "command_manifest": manifest, "capsule_ref": capsule_ref, "capsule": capsule,
            "commands": [dict(command_by_id[command_id]) for command_id in order],
            "task_bundle_ref": task_ref, "task_bundle": task_bundle,
        })
    return {"dag": dag, "node": dict(node), "index": index, "index_ref": index_ref,
            "units": units, "source_refs": sorted(source_refs)}


def plan_workpack_node(candidate_root: Path, node_id: str) -> dict[str, Any]:
    """Expose the declared ordered plan without creating any execution state."""
    _require(not candidate_root.is_symlink(), "WORKPACK_PLAN_INVALID", "Candidate root is a symlink")
    candidate = candidate_root.resolve()
    identity = candidate_identity(candidate)
    plan = _load_workpack_plan(candidate, node_id)
    return {
        "status": "DECLARED_WORKPACK_PLAN", "candidate_tree_sha256": identity,
        "node_id": node_id, "program_id": plan["index"].get("program_id"),
        "required_predecessor_nodes": plan["node"].get("required_predecessor_nodes"),
        "units": plan["units"], "source_refs": plan["source_refs"],
        "execution_authorized": False, "writes_performed": False,
    }


def _load_candidate_contracts(candidate_root: Path) -> dict[str, Any]:
    plan = _load_workpack_plan(candidate_root, NODE_ID)
    _require(len(plan["units"]) == 1, "WORKPACK_PLAN_INVALID", "materialization requires one root Workpack")
    unit = plan["units"][0]
    dag, node, index = plan["dag"], plan["node"], plan["index"]
    workpack, command_manifest, capsule = unit["workpack"], unit["command_manifest"], unit["capsule"]
    workpack_id = unit["workpack_id"]
    runtime_contract = read_json(candidate_root / RUNTIME_CONTRACT_REF, "WORKPACK_RUNTIME_SOURCE_STATE_INVALID")
    _require(runtime_contract.get("node_id") == NODE_ID
             and runtime_contract.get("workpack_id") == workpack_id,
             "WORKPACK_RUNTIME_SOURCE_STATE_INVALID", "runtime contract differs from DAG Workpack binding")
    commands = command_manifest.get("commands")
    command_ids = [
        item.get("command_id") for item in commands or [] if isinstance(item, Mapping)
    ]
    _require(
        command_ids == list(COMMAND_IDS)
        and command_manifest.get("workpack_id") == workpack_id
        and command_manifest.get("execution_started") is False,
        "COMMAND_MANIFEST_INVALID",
        "planned Workpack commands are not exact",
    )
    _require(
        workpack.get("status") == "PLANNED_NOT_ACTIVE"
        and workpack.get("execution_authorization_ref") is None
        and workpack.get("validation_scope") == VALIDATION_SCOPE
        and node.get("workpack_id") == workpack_id
        and node.get("required_execution_mode") == "WORKPACK_EXECUTION"
        and node.get("required_authorization_scope")
        == "PROJECT_BOOTSTRAP_AUTHORIZATION"
        and node.get("validation_scope") == VALIDATION_SCOPE
        and capsule.get("workpack_id") == workpack_id
        and capsule.get("execution_authorized") is False
        and capsule.get("execution_authorization_ref") is None
        and capsule.get("hydration_complete") is False,
        "WORKPACK_RUNTIME_SOURCE_STATE_INVALID",
        "Candidate must remain planned and unauthorized before Runtime hydration",
    )
    refs = (
        DAG_REF,
        plan["index_ref"],
        unit["command_manifest_ref"],
        unit["capsule_ref"],
        PROVIDER_IMPLEMENTATION_REF,
        RUNTIME_ENTRYPOINT_REF,
        RUNTIME_CONTRACT_REF,
    )
    return {
        "dag": dag,
        "node": dict(node),
        "index": index,
        "workpack": dict(workpack),
        "command_manifest": command_manifest,
        "capsule": capsule,
        "source_sha256s": {
            relative: _manifest_file_hash(candidate_root, relative)
            for relative in refs
        },
    }


def _read_event_tip(path: Path) -> str | None:
    if not path.exists():
        return None
    previous: str | None = None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in lines:
            if not line.strip():
                continue
            event = json.loads(line)
            _require(
                isinstance(event, dict)
                and event.get("previous_event_hash") == previous
                and event.get("event_hash") == hash_without(event, "event_hash"),
                "CONTROL_EVENT_LEDGER_INVALID",
                "event Hash chain is invalid",
            )
            previous = str(event["event_hash"])
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeContractError("CONTROL_EVENT_LEDGER_INVALID", str(exc)) from None
    return previous


def _validate_control_binding(
    candidate_root: Path,
    execution_root: Path,
    candidate_sha256: str,
    contracts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    contracts = contracts or _load_candidate_contracts(candidate_root)
    predecessors = contracts["node"].get("required_predecessor_nodes")
    _require(isinstance(predecessors, list) and len(predecessors) == 1
             and isinstance(predecessors[0], str)
             and re.fullmatch(r"[A-Za-z0-9_-]+", predecessors[0]) is not None,
             "WORKPACK_PLAN_INVALID", "materialization must have one declared predecessor")
    predecessor_id = predecessors[0]
    state_path = execution_root / CONTROL_STATE_REF
    event_path = execution_root / CONTROL_EVENTS_REF
    predecessor_path = execution_root / f"evidence/engineering_dag/{predecessor_id}/result.json"
    state = read_json(state_path, "PROGRAM_CONTROL_STATE_INVALID")
    event_tip = _read_event_tip(event_path)
    _require(
        state.get("state_sha256") == hash_without(state, "state_sha256")
        and state.get("last_event_hash") == event_tip
        and state.get("last_completed_node") == predecessor_id
        and state.get("next_node") == NODE_ID
        and state.get("program_id") == contracts["index"].get("program_id")
        and state.get("driver_started") is False
        and state.get("active_workpack") is None
        and state.get("authorization_status") == "CONSUMED"
        and state.get("remaining_transition_budget") == 0,
        "PROGRAM_CONTROL_STATE_INVALID",
        "current control state is not the declared predecessor gate",
    )
    predecessor_code = (
        "PROGRAM_DRIVER_RUNTIME_VERIFICATION_RESULT_INVALID"
        if predecessor_id == "PROGRAM_DRIVER_RUNTIME_VERIFIED"
        else "WORKPACK_PREDECESSOR_RESULT_INVALID"
    )
    predecessor = read_json(predecessor_path, predecessor_code)
    _require(
        predecessor.get("status") == "PASS"
        and predecessor.get("node_id") == predecessor_id
        and predecessor.get("candidate_tree_sha256") == candidate_sha256
        and predecessor.get("next_node") == NODE_ID
        and predecessor.get("driver_started") is False
        and predecessor.get("workpack_started") is False,
        predecessor_code,
        "predecessor result is not bound to this Candidate and node",
    )
    return {
        "control_state_file_sha256": file_hash(state_path),
        "control_state_payload_sha256": str(state["state_sha256"]),
        "control_event_ledger_sha256": file_hash(event_path),
        "control_event_tip": event_tip,
        "predecessor_result_sha256": file_hash(predecessor_path),
        "next_fencing_token": state.get("next_fencing_token"),
        "revision": state.get("revision"),
        "program_id": state.get("program_id"),
    }


def verify_codex_cli_schema(
    executable: Path,
    executable_sha256: str,
    *,
    timeout_seconds: int = 20,
) -> dict[str, Any]:
    _require(
        executable.is_absolute()
        and executable.is_file()
        and not executable.is_symlink()
        and os.access(executable, os.X_OK),
        "COMMAND_OVERLAY_EXECUTABLE_INVALID",
        "Codex executable must be an absolute executable regular file",
    )
    _require(
        _is_sha256(executable_sha256)
        and file_hash(executable) == executable_sha256,
        "CODEX_HASH_MISMATCH",
        "Codex executable Hash drifted before schema verification",
    )
    completed = subprocess.run(
        [str(executable), "exec", "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env={"PATH": os.environ.get("PATH", "")},
    )
    help_text = f"{completed.stdout}\n{completed.stderr}"
    required_tokens = ("--sandbox", "--skip-git-repo-check")
    _require(
        completed.returncode == 0
        and all(token in help_text for token in required_tokens),
        "CODEX_CLI_SCHEMA_UNVERIFIED",
        "Codex exec CLI does not expose the required bounded flags",
    )
    return {
        "probe_argv": [str(executable), "exec", "--help"],
        "exit_code": completed.returncode,
        "required_tokens": list(required_tokens),
        "help_sha256": hashlib.sha256(help_text.encode("utf-8")).hexdigest(),
        "schema_verified": True,
    }


def _validate_overlay_command(
    item: Mapping[str, Any],
    *,
    command_id: str,
    repository_root: Path,
    allowed_roots: set[Path],
) -> dict[str, Any]:
    executable = Path(str(item.get("executable_abs") or ""))
    executable_sha256 = item.get("executable_sha256")
    argv = item.get("argv")
    cwd = Path(str(item.get("cwd_abs") or ""))
    writes = item.get("allowed_write_roots")
    _require(
        executable.is_absolute()
        and executable.is_file()
        and not executable.is_symlink()
        and os.access(executable, os.X_OK)
        and _is_sha256(executable_sha256)
        and file_hash(executable) == executable_sha256,
        "COMMAND_OVERLAY_EXECUTABLE_INVALID",
        command_id,
    )
    _require(
        isinstance(argv, list)
        and bool(argv)
        and all(isinstance(value, str) for value in argv)
        and argv[0] == str(executable),
        "COMMAND_OVERLAY_ARGV_INVALID",
        command_id,
    )
    _require(
        cwd.is_absolute() and cwd == repository_root,
        "COMMAND_OVERLAY_CWD_INVALID",
        command_id,
    )
    _require(
        isinstance(writes, list)
        and bool(writes)
        and all(isinstance(value, str) for value in writes)
        and all(Path(value).is_absolute() for value in writes)
        and {Path(value) for value in writes}.issubset(allowed_roots),
        "COMMAND_OVERLAY_WRITE_ROOT_INVALID",
        command_id,
    )
    if command_id == "ROOT-CODEX-CODING":
        sandbox_index = argv.index("--sandbox") if "--sandbox" in argv else -1
        _require(
            len(argv) >= 6
            and argv[1] == "exec"
            and sandbox_index >= 0
            and sandbox_index + 1 < len(argv)
            and argv[sandbox_index + 1] == "workspace-write"
            and "--skip-git-repo-check" in argv
            and not FORBIDDEN_CODEX_FLAGS.intersection(argv),
            "CODEX_CLI_SCHEMA_UNVERIFIED",
            "Codex argv is not the bounded workspace-write contract",
        )
    else:
        expected = ["-m", "unittest", "discover", "-s", "tests"]
        _require(
            all(token in argv for token in expected),
            "POSTFLIGHT_COMMAND_INVALID",
            "postflight must run the official unittest discovery",
        )
    normalized = {
        "command_id": command_id,
        "executable_abs": str(executable),
        "executable_sha256": str(executable_sha256),
        "argv": list(argv),
        "cwd_abs": str(cwd),
        "allowed_write_roots": [str(Path(value)) for value in writes],
        "network": "DENY",
        "shell": False,
    }
    normalized["resolved_command_sha256"] = json_hash(normalized)
    return normalized


def hydrate_workpack_runtime(
    candidate_root: Path,
    execution_root: Path,
    overlay: Mapping[str, Any],
    *,
    verify_cli_schema: bool = True,
) -> dict[str, Any]:
    """Resolve planned commands into a side-effect-free, A3-ready descriptor."""

    candidate, execution = _resolved_roots(candidate_root, execution_root)
    candidate_sha256 = candidate_identity(candidate)
    contracts = _load_candidate_contracts(candidate)
    control = _validate_control_binding(candidate, execution, candidate_sha256, contracts)
    repository_root = execution / REPOSITORY_REF
    evidence_root = execution / NODE_EVIDENCE_REF
    expected_write_roots = {repository_root, evidence_root}
    _require(
        overlay.get("schema_version") == "1.0"
        and overlay.get("node_id") == NODE_ID
        and overlay.get("workpack_id") == contracts["workpack"]["workpack_id"]
        and overlay.get("candidate_tree_sha256") == candidate_sha256
        and overlay.get("max_transitions") == MAX_TRANSITIONS
        and overlay.get("max_loop_rounds") == MAX_LOOP_ROUNDS
        and overlay.get("real_target_install_allowed") is False
        and overlay.get("validation_scope") == VALIDATION_SCOPE
        and set(Path(value) for value in overlay.get("allowed_write_roots") or [])
        == expected_write_roots,
        "COMMAND_OVERLAY_SCOPE_INVALID",
        "overlay scope, Candidate, budget, or write roots are not exact",
    )
    commands = overlay.get("commands")
    _require(
        isinstance(commands, list)
        and [item.get("command_id") for item in commands if isinstance(item, Mapping)]
        == list(COMMAND_IDS),
        "COMMAND_OVERLAY_INVALID",
        "exactly two ordered Workpack commands are required",
    )
    resolved = [
        _validate_overlay_command(
            item,
            command_id=command_id,
            repository_root=repository_root,
            allowed_roots=expected_write_roots,
        )
        for command_id, item in zip(COMMAND_IDS, commands, strict=True)
    ]
    cli_schema = (
        verify_codex_cli_schema(
            Path(resolved[0]["executable_abs"]),
            resolved[0]["executable_sha256"],
        )
        if verify_cli_schema
        else overlay.get("verified_cli_schema")
    )
    _require(
        isinstance(cli_schema, Mapping)
        and cli_schema.get("schema_verified") is True
        and _is_sha256(cli_schema.get("help_sha256")),
        "CODEX_CLI_SCHEMA_UNVERIFIED",
        "a verified Codex CLI schema binding is required",
    )
    descriptor: dict[str, Any] = {
        "schema_version": "1.0",
        "status": "READY_FOR_A3_PREPARATION",
        "assurance_profile": ASSURANCE_PROFILE,
        "program_id": control["program_id"],
        "node_id": NODE_ID,
        "workpack_id": contracts["workpack"]["workpack_id"],
        "candidate_tree_sha256": candidate_sha256,
        "candidate_source_sha256s": contracts["source_sha256s"],
        "provider_implementation_ref": PROVIDER_IMPLEMENTATION_REF,
        "provider_implementation_sha256": contracts["source_sha256s"][
            PROVIDER_IMPLEMENTATION_REF
        ],
        "runtime_entrypoint_ref": RUNTIME_ENTRYPOINT_REF,
        "runtime_entrypoint_sha256": contracts["source_sha256s"][
            RUNTIME_ENTRYPOINT_REF
        ],
        "runtime_contract_ref": RUNTIME_CONTRACT_REF,
        "runtime_contract_sha256": contracts["source_sha256s"][
            RUNTIME_CONTRACT_REF
        ],
        "control_binding": control,
        "resolved_commands": resolved,
        "resolved_command_sha256s": [
            item["resolved_command_sha256"] for item in resolved
        ],
        "codex_cli_schema": dict(cli_schema),
        "allowed_write_roots": sorted(str(path) for path in expected_write_roots),
        "max_transitions": MAX_TRANSITIONS,
        "max_loop_rounds": MAX_LOOP_ROUNDS,
        "real_target_install_allowed": False,
        "validation_scope": VALIDATION_SCOPE,
        "candidate_read_only": True,
        "execution_authorized": False,
        "workpack_executed": False,
        "hydration_sha256": "",
    }
    descriptor["hydration_sha256"] = hash_without(
        descriptor, "hydration_sha256"
    )
    return descriptor


def validate_a3_authorization(
    hydration: Mapping[str, Any], authorization: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate a fresh exact A3 without consuming or executing it."""

    required_fields = {
        "schema_version",
        "authorization_id",
        "authorization_class",
        "status",
        "one_shot",
        "program_id",
        "node_id",
        "workpack_id",
        "candidate_tree_sha256",
        "hydration_sha256",
        "resolved_command_sha256s",
        "provider_implementation_sha256",
        "codex_executable_sha256",
        "codex_cli_help_sha256",
        "allowed_write_roots",
        "max_transitions",
        "max_loop_rounds",
        "real_target_install_allowed",
        "validation_scope",
        "network_allowed",
        "target_install_allowed",
        "delegation_allowed",
        "not_before",
        "expires_at",
    }
    _require(
        set(authorization) == required_fields,
        "A3_AUTHORIZATION_INVALID",
        "A3 fields are not exact",
    )
    commands = hydration.get("resolved_commands")
    codex = commands[0] if isinstance(commands, list) and commands else {}
    schema = hydration.get("codex_cli_schema")
    expected = {
        "schema_version": "1.0",
        "authorization_class": AUTHORIZATION_CLASS,
        "status": "GRANTED",
        "one_shot": True,
        "program_id": hydration.get("program_id"),
        "node_id": NODE_ID,
        "workpack_id": hydration.get("workpack_id"),
        "candidate_tree_sha256": hydration.get("candidate_tree_sha256"),
        "hydration_sha256": hydration.get("hydration_sha256"),
        "resolved_command_sha256s": hydration.get("resolved_command_sha256s"),
        "provider_implementation_sha256": hydration.get(
            "provider_implementation_sha256"
        ),
        "codex_executable_sha256": codex.get("executable_sha256"),
        "codex_cli_help_sha256": (
            schema.get("help_sha256") if isinstance(schema, Mapping) else None
        ),
        "allowed_write_roots": hydration.get("allowed_write_roots"),
        "max_transitions": MAX_TRANSITIONS,
        "max_loop_rounds": MAX_LOOP_ROUNDS,
        "real_target_install_allowed": False,
        "validation_scope": VALIDATION_SCOPE,
        "network_allowed": False,
        "target_install_allowed": False,
        "delegation_allowed": False,
    }
    for field, value in expected.items():
        _require(
            authorization.get(field) == value,
            "A3_AUTHORIZATION_INVALID",
            field,
        )
    try:
        not_before = datetime.fromisoformat(
            str(authorization["not_before"]).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        expires_at = datetime.fromisoformat(
            str(authorization["expires_at"]).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    except ValueError:
        raise RuntimeContractError(
            "A3_AUTHORIZATION_INVALID", "authorization validity is invalid"
        ) from None
    now = datetime.now(timezone.utc)
    _require(
        not_before <= now < expires_at,
        "A3_AUTHORIZATION_INVALID",
        "authorization is outside its validity window",
    )
    return dict(authorization)


def _tree_snapshot(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    if not root.exists():
        return snapshot
    for path in sorted(root.rglob("*")):
        _require(
            not path.is_symlink(),
            "RUNTIME_WRITE_CONTAINMENT_INVALID",
            f"symlink is forbidden: {path}",
        )
        if path.is_file():
            snapshot[path.relative_to(root).as_posix()] = file_hash(path)
    return snapshot


def _run_command(command: Mapping[str, Any], timeout_seconds: int) -> dict[str, Any]:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(
        list(command["argv"]),
        cwd=command["cwd_abs"],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=environment,
    )
    return {
        "command_id": command["command_id"],
        "resolved_command_sha256": command["resolved_command_sha256"],
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _write_new_file(path: Path, content: bytes) -> None:
    """Publish one evidence file atomically without replacing prior evidence."""

    path.parent.mkdir(parents=True, exist_ok=True)
    _require(
        not path.exists() and not path.is_symlink(),
        "RUNTIME_OUTPUT_COLLISION",
        str(path),
    )
    suffix = hashlib.sha256(content).hexdigest()[:16]
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{suffix}")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    except FileExistsError as exc:
        raise RuntimeContractError("RUNTIME_OUTPUT_COLLISION", str(path)) from exc
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _write_json_evidence(path: Path, value: Mapping[str, Any]) -> None:
    _write_new_file(
        path,
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n",
    )


def _structural_postflight(repository_root: Path) -> dict[str, Any]:
    files = _tree_snapshot(repository_root)
    required = {"pyproject.toml", "src", "tests"}
    top_level = {Path(relative).parts[0] for relative in files}
    status = "PASS" if required.issubset(top_level) else "FAIL"
    result = {
        "status": status,
        "validation_scope": VALIDATION_SCOPE,
        "required_top_level_entries": sorted(required),
        "observed_top_level_entries": sorted(top_level),
        "file_count": len(files),
        "tree_sha256": json_hash(files),
    }
    result["review_sha256"] = json_hash(result)
    return result


def execute_hydrated_workpack(
    candidate_root: Path,
    execution_root: Path,
    hydration: Mapping[str, Any],
    authorization: Mapping[str, Any],
    *,
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    """Execute one authorized Workpack; never advances the successor node."""

    candidate, execution = _resolved_roots(candidate_root, execution_root)
    _require(not (execution / ".harness-foundry/control.sqlite3").exists(),
             "SQLITE_CONTROLLER_OWNS_STATE", "legacy Workpack execution cannot bypass the authoritative SQLite controller")
    _require(
        hydration.get("hydration_sha256")
        == hash_without(hydration, "hydration_sha256")
        and hydration.get("status") == "READY_FOR_A3_PREPARATION"
        and hydration.get("candidate_tree_sha256") == candidate_identity(candidate),
        "RUNTIME_HYDRATION_INVALID",
        "hydration is stale or malformed",
    )
    validate_a3_authorization(hydration, authorization)
    commands = hydration.get("resolved_commands")
    _require(
        isinstance(commands, list) and len(commands) == 2,
        "RUNTIME_HYDRATION_INVALID",
        "resolved commands are missing",
    )
    repository_root = execution / REPOSITORY_REF
    evidence_root = execution / NODE_EVIDENCE_REF
    _require(
        set(hydration.get("allowed_write_roots") or [])
        == {str(repository_root), str(evidence_root)},
        "RUNTIME_WRITE_CONTAINMENT_INVALID",
        "hydrated write roots are not exact",
    )
    _require(
        not repository_root.exists() and not evidence_root.exists(),
        "RUNTIME_OUTPUT_COLLISION",
        "repository and node evidence roots must be fresh and absent",
    )
    # Hydration may wait for human authorization. Its self-hash proves what was
    # prepared, not that the control state or executable bytes are still current.
    contracts = _load_candidate_contracts(candidate)
    control = _validate_control_binding(
        candidate, execution, hydration["candidate_tree_sha256"], contracts
    )
    _require(
        contracts["source_sha256s"] == hydration.get("candidate_source_sha256s")
        and contracts["workpack"]["workpack_id"] == hydration.get("workpack_id")
        and control == hydration.get("control_binding"),
        "RUNTIME_HYDRATION_STALE",
        "Candidate contracts or control state changed after hydration; prepare again",
    )
    current_commands = [
        _validate_overlay_command(
            command,
            command_id=command_id,
            repository_root=repository_root,
            allowed_roots={repository_root, evidence_root},
        )
        for command_id, command in zip(COMMAND_IDS, commands, strict=True)
    ]
    _require(
        current_commands == commands
        and [item["resolved_command_sha256"] for item in current_commands]
        == hydration.get("resolved_command_sha256s"),
        "RUNTIME_HYDRATION_STALE",
        "resolved commands no longer match the authorized hydration",
    )
    candidate_before = _tree_snapshot(candidate)
    execution_before = _tree_snapshot(execution)
    repository_root.mkdir(parents=True)
    evidence_root.mkdir(parents=True)
    command_results: list[dict[str, Any]] = []
    for command in commands:
        command_result = _run_command(command, timeout_seconds)
        command_id = str(command_result["command_id"])
        stdout_path = evidence_root / f"{command_id}.stdout.txt"
        stderr_path = evidence_root / f"{command_id}.stderr.txt"
        _write_new_file(stdout_path, str(command_result.pop("stdout")).encode("utf-8"))
        _write_new_file(stderr_path, str(command_result.pop("stderr")).encode("utf-8"))
        command_result.update(
            {
                "stdout_ref": stdout_path.relative_to(execution).as_posix(),
                "stdout_sha256": file_hash(stdout_path),
                "stderr_ref": stderr_path.relative_to(execution).as_posix(),
                "stderr_sha256": file_hash(stderr_path),
            }
        )
        command_result["command_result_sha256"] = json_hash(command_result)
        _write_json_evidence(
            evidence_root / f"{command_id}.result.json",
            command_result,
        )
        command_results.append(command_result)
        if command_result["exit_code"] != 0:
            break
    postflight = _structural_postflight(repository_root)
    verification_command = (
        command_results[1] if len(command_results) == 2 else None
    )
    independent_review = _structural_postflight(repository_root)
    independent_review.update(
        {
            "reviewer_id": "CONTROLLED_RUNTIME_STRUCTURAL_REVIEW_V1",
            "verification_command_sha256": (
                verification_command.get("resolved_command_sha256")
                if isinstance(verification_command, Mapping)
                else None
            ),
            "verification_exit_code": (
                verification_command.get("exit_code")
                if isinstance(verification_command, Mapping)
                else None
            ),
        }
    )
    independent_review["review_sha256"] = hash_without(
        independent_review, "review_sha256"
    )
    if independent_review["verification_exit_code"] != 0:
        independent_review["status"] = "FAIL"
        independent_review["review_sha256"] = hash_without(
            independent_review, "review_sha256"
        )
    _write_json_evidence(evidence_root / "POSTFLIGHT.json", postflight)
    _write_json_evidence(
        evidence_root / "INDEPENDENT_REVIEW.json",
        independent_review,
    )
    _require(
        candidate_before == _tree_snapshot(candidate),
        "CANDIDATE_MUTATED_DURING_WORKPACK",
        "Candidate bytes changed during Workpack execution",
    )
    execution_after = _tree_snapshot(execution)
    changed = {
        relative
        for relative in set(execution_before) | set(execution_after)
        if execution_before.get(relative) != execution_after.get(relative)
    }
    allowed_prefixes = (f"{REPOSITORY_REF}/", f"{NODE_EVIDENCE_REF}/")
    _require(
        all(relative.startswith(allowed_prefixes) for relative in changed),
        "RUNTIME_WRITE_CONTAINMENT_INVALID",
        "Workpack changed a file outside its exact write roots",
    )
    status = (
        "PASS"
        if len(command_results) == 2
        and all(item["exit_code"] == 0 for item in command_results)
        and postflight["status"] == "PASS"
        and independent_review["status"] == "PASS"
        else "FAIL"
    )
    result: dict[str, Any] = {
        "schema_version": "1.0",
        "status": status,
        "program_id": hydration.get("program_id"),
        "node_id": NODE_ID,
        "workpack_id": contracts["workpack"]["workpack_id"],
        "candidate_tree_sha256": hydration.get("candidate_tree_sha256"),
        "hydration_sha256": hydration.get("hydration_sha256"),
        "authorization_id": authorization.get("authorization_id"),
        "authorization_sha256": json_hash(authorization),
        "command_results": command_results,
        "postflight": postflight,
        "independent_review": independent_review,
        "loop_rounds_consumed": 0,
        "max_loop_rounds": MAX_LOOP_ROUNDS,
        "max_transitions": MAX_TRANSITIONS,
        "real_target_install_allowed": False,
        "validation_scope": VALIDATION_SCOPE,
        "produced_capabilities": (
            [
                "MAIN_EXECUTION_PACKAGE_MATERIALIZED_PASS",
                "MAIN_EXECUTION_PACKAGE_MATERIALIZED_READY",
            ]
            if status == "PASS"
            else []
        ),
        "successor_started": False,
        "result_sha256": "",
    }
    result["result_sha256"] = hash_without(result, "result_sha256")
    _write_json_evidence(evidence_root / "result.json", result)
    execution_after_result = _tree_snapshot(execution)
    changed_after_result = {
        relative
        for relative in set(execution_before) | set(execution_after_result)
        if execution_before.get(relative) != execution_after_result.get(relative)
    }
    _require(
        all(relative.startswith(allowed_prefixes) for relative in changed_after_result),
        "RUNTIME_WRITE_CONTAINMENT_INVALID",
        "Workpack evidence changed a file outside its exact write roots",
    )
    return result


__all__ = [
    "RuntimeContractError",
    "candidate_identity",
    "execute_hydrated_workpack",
    "hydrate_workpack_runtime",
    "plan_workpack_node",
    "validate_a3_authorization",
    "verify_codex_cli_schema",
]
