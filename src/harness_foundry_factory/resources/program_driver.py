#!/usr/bin/env python3
"""Portable read-only Program Driver pre-verification entrypoint.

Only ``status``, ``plan-next``, and ``validate-transition`` are available before
the runtime-verification gate.  The entrypoint never writes control state,
starts the Driver loop, or executes a Workpack.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping


sys.dont_write_bytecode = True
TOOLS_ROOT = Path(__file__).resolve().parent
_BASE_PATH = TOOLS_ROOT / "shared_control_baseline.py"
_BASE_SPEC = importlib.util.spec_from_file_location(
    "harness_foundry_program_driver_base", _BASE_PATH
)
if _BASE_SPEC is None or _BASE_SPEC.loader is None:
    raise RuntimeError("portable Shared Control Baseline runtime is missing")
base = importlib.util.module_from_spec(_BASE_SPEC)
_BASE_SPEC.loader.exec_module(base)


NODE_ID = "PROGRAM_DRIVER_RUNTIME_VERIFIED"
PREDECESSOR_NODE_ID = "CONTROL_PLANE_REGISTRATION"
PREDECESSOR_REF = (
    "evidence/engineering_dag/CONTROL_PLANE_REGISTRATION/result.json"
)
CONTROL_STATE_REF = base.CONTROL_STATE_REF
CONTROL_EVENTS_REF = base.CONTROL_EVENTS_REF
READ_ONLY_COMMANDS = ("status", "plan-next", "validate-transition")


ContractError = base.ContractError
candidate_identity = base.candidate_identity
file_hash = base.file_hash
hash_without = base.hash_without
json_hash = base.json_hash
read_events = base.read_events
read_json = base.read_json
require_equal = base.require_equal


def _resolve_roots(
    candidate_root: Path, execution_root: Path
) -> tuple[Path, Path]:
    if candidate_root.is_symlink() or execution_root.is_symlink():
        raise ContractError(
            "PROGRAM_DRIVER_READ_ONLY_CONTEXT_INVALID",
            "Candidate and Execution Root symlinks are forbidden",
        )
    candidate = candidate_root.resolve()
    execution = execution_root.resolve()
    if (
        candidate == execution
        or candidate in execution.parents
        or execution in candidate.parents
    ):
        raise ContractError(
            "PROGRAM_DRIVER_READ_ONLY_CONTEXT_INVALID",
            "Candidate and Execution Root must be disjoint",
        )
    return candidate, execution


def _read_context(
    candidate_root: Path, execution_root: Path
) -> dict[str, Any]:
    candidate, execution = _resolve_roots(candidate_root, execution_root)
    state_path = execution / CONTROL_STATE_REF
    event_path = execution / CONTROL_EVENTS_REF
    state = read_json(state_path, "PROGRAM_CONTROL_STATE_INVALID")
    require_equal(
        state.get("state_sha256"),
        hash_without(state, "state_sha256"),
        "PROGRAM_CONTROL_STATE_INVALID",
        "state_sha256",
    )
    require_equal(
        state.get("driver_started"),
        False,
        "PROGRAM_DRIVER_ALREADY_STARTED",
        "driver_started",
    )
    require_equal(
        state.get("active_workpack"),
        None,
        "PROGRAM_WORKPACK_ALREADY_ACTIVE",
        "active_workpack",
    )
    events = read_events(event_path)
    event_tip = events[-1].get("event_hash") if events else None
    require_equal(
        state.get("last_event_hash"),
        event_tip,
        "CONTROL_EVENT_LEDGER_INVALID",
        "last_event_hash",
    )
    dag = read_json(
        candidate / "ENGINEERING_PROJECT_DAG.json",
        "ENGINEERING_PROJECT_DAG_INVALID",
    )
    nodes = dag.get("nodes")
    if not isinstance(nodes, list):
        raise ContractError(
            "ENGINEERING_PROJECT_DAG_INVALID", "nodes must be a list"
        )
    node = next(
        (
            item
            for item in nodes
            if isinstance(item, Mapping)
            and item.get("node_id") == state.get("next_node")
        ),
        None,
    )
    if not isinstance(node, Mapping):
        raise ContractError(
            "ENGINEERING_PROJECT_DAG_INVALID",
            "next_node is not declared in the DAG",
        )
    return {
        "candidate_root": candidate,
        "execution_root": execution,
        "candidate_tree_sha256": candidate_identity(candidate),
        "state": state,
        "state_file_sha256": file_hash(state_path),
        "event_tip": event_tip,
        "node": dict(node),
    }


def _base_result(command: str, context: Mapping[str, Any]) -> dict[str, Any]:
    state = context["state"]
    result = {
        "schema_version": "1.0",
        "status": "PASS",
        "command": command,
        "read_only": True,
        "program_id": state.get("program_id"),
        "candidate_tree_sha256": context["candidate_tree_sha256"],
        "control_state_file_sha256": context["state_file_sha256"],
        "control_state_payload_sha256": state.get("state_sha256"),
        "event_tip": context["event_tip"],
        "revision": state.get("revision"),
        "last_completed_node": state.get("last_completed_node"),
        "next_node": state.get("next_node"),
        "driver_started": False,
        "workpack_started": False,
        "active_workpack": None,
        "probe_sha256": "",
    }
    result["probe_sha256"] = hash_without(result, "probe_sha256")
    return result


def status(candidate_root: Path, execution_root: Path) -> dict[str, Any]:
    return _base_result(
        "status", _read_context(candidate_root, execution_root)
    )


def plan_next(candidate_root: Path, execution_root: Path) -> dict[str, Any]:
    context = _read_context(candidate_root, execution_root)
    node = context["node"]
    result = _base_result("plan-next", context)
    result.update(
        {
            "eligible": context["state"].get("next_node") == NODE_ID,
            "required_authorization_scope": node.get(
                "required_authorization_scope"
            ),
            "required_execution_mode": node.get("required_execution_mode"),
            "successor_node": (
                list(node.get("allowed_next_nodes") or [None])[0]
            ),
            "probe_sha256": "",
        }
    )
    result["probe_sha256"] = hash_without(result, "probe_sha256")
    return result


def validate_transition(
    candidate_root: Path, execution_root: Path
) -> dict[str, Any]:
    context = _read_context(candidate_root, execution_root)
    state = context["state"]
    node = context["node"]
    require_equal(
        state.get("last_completed_node"),
        PREDECESSOR_NODE_ID,
        "PROGRAM_DRIVER_TRANSITION_NOT_ELIGIBLE",
        "last_completed_node",
    )
    require_equal(
        state.get("next_node"),
        NODE_ID,
        "PROGRAM_DRIVER_TRANSITION_NOT_ELIGIBLE",
        "next_node",
    )
    require_equal(
        node.get("required_execution_mode"),
        "PROJECT_VALIDATION",
        "PROGRAM_DRIVER_TRANSITION_NOT_ELIGIBLE",
        "required_execution_mode",
    )
    require_equal(
        node.get("required_authorization_scope"),
        "PROJECT_VALIDATION_AUTHORIZATION",
        "PROGRAM_DRIVER_TRANSITION_NOT_ELIGIBLE",
        "required_authorization_scope",
    )
    predecessor_path = context["execution_root"] / PREDECESSOR_REF
    predecessor = read_json(
        predecessor_path, "CONTROL_PLANE_REGISTRATION_RESULT_INVALID"
    )
    require_equal(
        predecessor.get("status"),
        "PASS",
        "CONTROL_PLANE_REGISTRATION_RESULT_INVALID",
        "status",
    )
    require_equal(
        predecessor.get("node_id"),
        PREDECESSOR_NODE_ID,
        "CONTROL_PLANE_REGISTRATION_RESULT_INVALID",
        "node_id",
    )
    require_equal(
        predecessor.get("candidate_tree_sha256"),
        context["candidate_tree_sha256"],
        "CONTROL_PLANE_REGISTRATION_RESULT_INVALID",
        "candidate_tree_sha256",
    )
    result = _base_result("validate-transition", context)
    result.update(
        {
            "transition_valid": True,
            "predecessor_node": PREDECESSOR_NODE_ID,
            "predecessor_result_sha256": file_hash(predecessor_path),
            "required_authorization_scope": node.get(
                "required_authorization_scope"
            ),
            "required_execution_mode": node.get("required_execution_mode"),
            "probe_sha256": "",
        }
    )
    result["probe_sha256"] = hash_without(result, "probe_sha256")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=READ_ONLY_COMMANDS)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--execution-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        handlers = {
            "status": status,
            "plan-next": plan_next,
            "validate-transition": validate_transition,
        }
        output = handlers[args.command](
            args.candidate_root, args.execution_root
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
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
