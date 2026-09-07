"""Candidate-owned project verification recipes and runtime observations.

The verifier runs inside the existing approved offline receiver. Protocol
behavior evidence is not full Workpack acceptance or a successor capability.
No project implementation is imported into this controller module.
"""

from copy import deepcopy
import json


COMMAND_ID = "LAB-PROTOCOL-CHECK"
WORKER_REF = "harness-resource://candidate/tools/lab_protocol_worker.py"
PROJECT_REF = "harness-resource://execution/project_start_packages/external_lab/repository"
SCHEMA_REF = "harness-resource://candidate/validation/PUBLIC_SKILL_JOB_INTERFACE.json"


def lab_protocol_command():
    executable = "harness-resource://execution/project_start_packages/external_lab/.venv/bin/python"
    return {
        "command_id": COMMAND_ID, "command_kind": "CANDIDATE_PROJECT_VERIFICATION_COMMAND",
        "executor_role": "INDEPENDENT_PROJECT_VERIFIER", "executable": executable,
        "executable_abs": executable, "executable_status": "PLANNED_NOT_INSTALLED",
        "argv": [executable, "-I", "-B", WORKER_REF, "--project-root", PROJECT_REF, "--schema-file", SCHEMA_REF],
        "invocation_contract_status": "LOCKED_CANDIDATE_VERIFICATION_RECIPE",
        "cwd_absolute": PROJECT_REF, "authorization_ref": None,
        "preflight_gate": "COMMITTED_NATIVE_CODING_AND_APPROVED_OFFLINE_PARENT",
        "allowed_modes": ["WORKPACK_EXECUTION"], "expected_exit_codes": [0],
        "stdout_stderr_evidence_required": True, "allowed_write_roots": [],
        "allowed_read_roots": ["harness-resource://candidate", PROJECT_REF],
        "auto_execute": False, "shell": False,
        "verification_contract": {
            "protocol": "LAB_PROTOCOL_BEHAVIOR_V1", "node_id": "LAB_BOOTSTRAP",
            "workpack_id": "LAB-PROTOCOL", "worker_ref": WORKER_REF,
            "project_repository_ref": PROJECT_REF, "project_api_module": "external_lab.protocol",
            "schema_ref": SCHEMA_REF, "evidence_scope": "LAB_PROTOCOL_PRIMITIVES_ONLY",
            "workpack_accepted": False,
        },
    }


def plan_project_verification(candidate_root, node_id, workpack_id, command_id):
    from .workpack_acceptance import plan_workpack_completion, _require
    plan = plan_workpack_completion(candidate_root, node_id, workpack_id)
    commands = [command for command in plan["unit"]["commands"] if command["command_id"] == command_id]
    _require(len(commands) == 1 and command_id == COMMAND_ID, "select a supported native independent verification command")
    native = commands[0]
    contract = native.get("verification_contract")
    _require(contract == lab_protocol_command()["verification_contract"]
             and contract["node_id"] == node_id and contract["workpack_id"] == workpack_id
             and native.get("argv") == lab_protocol_command()["argv"]
             and native.get("executor_role") == "INDEPENDENT_PROJECT_VERIFIER"
             and native.get("allowed_write_roots") == [] and not native.get("job_artifact_lease_required"),
             "independent verifier contract or read-only ownership differs")
    _require(plan["semantic_contract"] is not None, "verification requires the complete native task bundle")
    return {"status": "DECLARED_PROJECT_VERIFICATION", "completion_plan": plan,
            "native_command": deepcopy(native), "cwd_ref": PROJECT_REF,
            "argv_tail": ["-I", "-B", {"resource_ref": WORKER_REF}, "--project-root",
                          {"resource_ref": PROJECT_REF}, "--schema-file", {"resource_ref": SCHEMA_REF}],
            "execution_authorized": False, "workpack_accepted": False, "writes_performed": False}


def validate_verification_invocation(parent, invocation, *, events=None):
    """Check fresh native selection and committed coding evidence before dispatch."""
    from .control_kernel import START_PACKAGE_BINDING_KIND, ControlKernelError
    from .workpack_acceptance import _command_observations
    from .workpack_runtime import RuntimeContractError
    native = invocation["native_command"]
    if native.get("command_id") != COMMAND_ID and native.get("executor_role") != "INDEPENDENT_PROJECT_VERIFIER":
        return None
    def require(condition, message):
        if not condition:
            raise ControlKernelError("PROJECT_VERIFICATION_BINDING_INVALID", message)
    require(parent.get("bindings", {}).get("binding_kind") == START_PACKAGE_BINDING_KIND,
            "project verification requires the audited live Candidate binding")
    contract = native.get("verification_contract", {})
    try:
        verification = plan_project_verification(parent["local_execution"]["candidate_root"],
            contract.get("node_id"), invocation["workpack_id"], native["command_id"])
    except RuntimeContractError as exc:
        raise ControlKernelError(exc.code, str(exc)) from exc
    plan = verification["completion_plan"]
    require(plan["candidate_tree_sha256"] == parent["bindings"]["candidate_tree_sha256"]
            and plan["project_id"] == invocation["project_id"] and verification["native_command"] == native
            and invocation["job_id"] is None and invocation["cwd_ref"] == verification["cwd_ref"]
            and invocation["argv"][1:] == verification["argv_tail"],
            "verification cannot replace the worker, project, schema or native command")
    if events is not None:
        prior = plan["command_execution_order"][:plan["command_execution_order"].index(native["command_id"])]
        observations = {row["command_id"]: row for row in _command_observations(events, plan)}
        require(prior == ["LAB-CODEX-CODING"] and all(observations[key]["status"] == "OBSERVED" for key in prior),
                "native coding must be genuinely observed and committed before project verification")
    return verification


def observe_project_verification(process_result):
    """Parse the independent worker's captured result, never an output file."""
    from .lab_protocol_checks import PROTOCOL_CASE_IDS
    try:
        report = json.loads(process_result["stdout"])
        rows = report["cases"]
        valid = (process_result.get("status") == "PASS" and process_result.get("exit_code") == 0
                 and process_result.get("timed_out") is False and not process_result.get("output_truncated")
                 and report.get("status") == "PASS" and report.get("evidence_scope") == "LAB_PROTOCOL_PRIMITIVES_ONLY"
                 and report.get("workpack_accepted") is False and report.get("execution_authorized") is False
                 and report.get("implementation_module") == "external_lab.protocol"
                 and isinstance(rows, list) and [row.get("case_id") for row in rows] == list(PROTOCOL_CASE_IDS)
                 and all(row.get("status") == "PASS" for row in rows))
    except (KeyError, ValueError, TypeError, AttributeError):
        report, valid = {}, False
    return {"status": "PASS" if valid else "FAIL", "report": report,
            "evidence_scope": "LAB_PROTOCOL_PRIMITIVES_ONLY", "workpack_accepted": False}
