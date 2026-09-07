"""Read-only handoff from audited pre-build approval to a separate runtime.

The Factory remains an authoring service. This projection carries a decision,
not permission to execute it. A later runtime must obtain its own authorization
and revalidate the live Factory binding before consuming the projection.
"""

from copy import deepcopy
import json
from pathlib import Path

from .models import FactoryError, content_sha256
from .control_kernel import START_PACKAGE_BINDING_KIND
from .prebuild_delegation import APPROVED_STOP, DELEGATE
from .resources.shared_control_baseline import ContractError, candidate_identity


RECEIPT_KIND = "FACTORY_CANDIDATE_APPROVAL_PROJECTION_V1"
APPROVAL_RECEIPT_REF = (
    "harness-resource://execution/evidence/engineering_dag/"
    "START_PACKAGE_HUMAN_APPROVAL/result.json"
)
STARTUP_NODES = (
    "SHARED_CONTROL_BASELINE_LOCK",
    "CONTROL_PLANE_REGISTRATION",
    "PROGRAM_DRIVER_RUNTIME_VERIFIED",
)


class ExecutionHandoffError(FactoryError):
    code = "EXECUTION_HANDOFF_BLOCKED"


def _require(condition, reason, message):
    if not condition:
        raise ExecutionHandoffError(message, details={"reason": reason})


def prepare_execution_handoff(service, program_id):
    """Read the live Factory and Candidate; never write or issue a grant."""
    # Import here to avoid coupling the authoring service's module initialization
    # to a runtime adapter. The digest domain is the existing Factory tree hash.
    from .service import _tree_hash

    record = service.store.get_program(program_id)
    snapshot = record.snapshot
    _require(service.verify_run(program_id)["status"] == "PASS",
             "FACTORY_AUDIT_INVALID", "Factory event or authority verification failed")
    _require(record.factory_state == APPROVED_STOP,
             "CANDIDATE_DECISION_REQUIRED", "a current audited Candidate approval is required")
    decision = snapshot.get("candidate_decision") or {}
    actor = decision.get("actor") or {}
    _require(decision.get("decision") == "APPROVE"
             and decision.get("approval_mode") == "DELEGATED"
             and actor.get("type") == DELEGATE
             and decision.get("execution_authorized") is False
             and decision.get("status") != "INVALIDATED_BY_REOPEN",
             "CANDIDATE_DECISION_INVALID", "only the recorded delegated approval can be projected")
    grant = snapshot.get("prebuild_delegations", {}).get(actor.get("delegation_id"), {})
    _require(grant.get("status") == "COMPLETED",
             "PREBUILD_GRANT_NOT_COMPLETED", "the approved decision must retain its completed pre-build grant")

    events = service.store.list_events(program_id)
    matches = [event for event in events
               if f"factory-event://{program_id}/{event['request_id']}" == decision.get("decision_event_ref")]
    _require(len(matches) == 1, "DECISION_EVENT_MISSING", "decision event does not resolve uniquely")
    event = matches[0]
    _require(event["event_type"] == "CANDIDATE_DECIDED_BY_DELEGATE"
             and event["actor"] == actor
             and event["resulting_snapshot"].get("candidate_decision") == decision
             and event["payload"].get("decision") == "APPROVE",
             "DECISION_EVENT_MISMATCH", "decision projection differs from the authoritative event")

    candidate = snapshot.get("candidate") or {}
    root = Path(candidate.get("candidate_path") or "")
    _require(root.is_absolute() and root.is_dir() and not root.is_symlink(),
             "CANDIDATE_ROOT_INVALID", "Candidate must be the published physical directory")
    _require(str(root) == snapshot["requirement_ir"]["target"]["output_root"],
             "CANDIDATE_ROOT_STALE", "Candidate root differs from the frozen output binding")
    digest, count = _tree_hash(root)
    requirement_digest = content_sha256(snapshot["requirement_ir"])
    _require(snapshot.get("freeze", {}).get("status") == "FROZEN"
             and digest == decision.get("candidate_content_sha256")
             and digest == candidate.get("compiler_result", {}).get("content_sha256")
             and count == candidate.get("compiler_result", {}).get("file_count")
             and requirement_digest == decision.get("requirement_ir_sha256")
             and requirement_digest == candidate.get("requirement_ir_sha256"),
             "CANDIDATE_BINDING_STALE", "published bytes or Requirement no longer match the approved decision")
    validation = service.validate_program_candidate(program_id)
    if validation.get("status") != "PASS" or validation.get("blocking_findings"):
        raise ExecutionHandoffError("current Candidate validation must pass before handoff", details={
            "reason": "CANDIDATE_VALIDATION_FAILED",
            "finding_codes": sorted({finding["code"] for finding in validation.get("blocking_findings", [])}),
        })

    dag = json.loads((root / "ENGINEERING_PROJECT_DAG.json").read_text(encoding="utf-8"))
    bindings = []
    for node_id in STARTUP_NODES:
        nodes = [node for node in dag.get("nodes", []) if node.get("node_id") == node_id]
        _require(len(nodes) == 1, "STARTUP_NODE_MISSING", node_id)
        node = nodes[0]
        refs = {field: node.get(field) for field in (
            "executor_implementation_ref", "action_contract_ref", "result_schema_ref")}
        _require(all(isinstance(ref, str) and (root / ref).resolve().is_relative_to(root.resolve())
                     and (root / ref).is_file() for ref in refs.values()),
                 "STARTUP_PROVIDER_MISSING", f"{node_id} has no complete packaged provider")
        bindings.append({"node_id": node_id, **refs})

    try:
        portable_digest = candidate_identity(root)
    except ContractError as exc:
        raise ExecutionHandoffError(str(exc), details={"reason": exc.code}) from exc
    _require(service.store.get_program(program_id).state_hash == record.state_hash,
             "FACTORY_STATE_CHANGED", "Factory state changed while preparing handoff; read again")
    _require(_tree_hash(root) == (digest, count),
             "CANDIDATE_CHANGED", "Candidate changed while preparing handoff")
    # The legacy first-control wire field is named candidate_tree_sha256 but
    # actually consumes the portable file inventory digest. Keep both domains
    # explicit; never compare that value to the Factory publication digest.
    receipt = {
        "schema_version": "1.0", "receipt_kind": RECEIPT_KIND,
        "receipt_id": f"FACTORY-APPROVAL-{program_id}-E{snapshot['requirement_epoch']}",
        "decision": "APPROVED", "approval_mode": "DELEGATED",
        "program_id": program_id,
        "candidate_tree_sha256": portable_digest,
        "candidate_identity_domain": "PORTABLE_FILE_MANIFEST_FILES",
        "factory_candidate_content_sha256": digest,
        "requirement_ir_sha256": requirement_digest,
        "factory_revision": record.revision, "factory_state_hash": record.state_hash,
        "decision_event_ref": decision["decision_event_ref"],
        "decided_at": decision["decided_at"], "actor": deepcopy(actor),
        "delegation_grant_ref": grant["approval_event_ref"],
        "next_node": STARTUP_NODES[0],
        "execution_authorized": False, "driver_start_authorized": False,
        "workpack_execution_authorized": False, "target_install_authorized": False,
    }
    return {
        "status": "PREBUILD_APPROVAL_VERIFIED_EXECUTION_NOT_AUTHORIZED",
        "program_id": program_id, "requirement_epoch": snapshot["requirement_epoch"],
        "candidate_root": str(root), "approval_receipt_ref": APPROVAL_RECEIPT_REF,
        "approval_receipt": receipt, "startup_bindings": bindings,
        "runtime_bindings": {
            "binding_kind": START_PACKAGE_BINDING_KIND, "program_id": program_id,
            "requirement_epoch": snapshot["requirement_epoch"],
            "architecture_epoch": snapshot["requirement_ir"]["target"].get("architecture_epoch"),
            "control_plane_epoch": snapshot["requirement_ir"]["target"].get("control_plane_epoch"),
            **{field: receipt[field] for field in ("requirement_ir_sha256", "candidate_tree_sha256",
                "factory_candidate_content_sha256", "factory_state_hash", "decision_event_ref")},
        },
        "next_required_action": "EXPLICIT_EXECUTION_AUTHORIZATION",
        "writes_performed": False, "execution_started": False,
    }


def validate_live_handoff(service, program_id, handoff):
    """A projection is not a reusable bearer grant; check it against live state."""
    current = prepare_execution_handoff(service, program_id)
    _require(current == handoff, "HANDOFF_STALE", "handoff no longer matches live Factory approval and Candidate")
    return current


def verify_runtime_factory_binding(parent):
    """Re-read the approved locator, not a caller-supplied PASS or cached receipt."""
    from .constants import default_spec_root
    from .service import FactoryService
    from .store import SQLiteEventStore

    plan = parent.get("startup_execution", parent.get("local_execution"))
    source = plan["factory_source"]
    service = FactoryService(SQLiteEventStore(source["database_path"], read_only=True),
                             spec_root=default_spec_root(), runs_root=source["runs_root"])
    current = prepare_execution_handoff(service, parent["program_id"])
    _require(current["candidate_root"] == plan["candidate_root"], "HANDOFF_ROOT_MISMATCH",
             "approved local root is not the live published Candidate")
    _require(current["runtime_bindings"] == parent["bindings"], "HANDOFF_STALE",
             "approved runtime binding no longer matches live Factory state")
    if "startup_execution" in parent:
        _require(current["approval_receipt"] == plan["approval_receipt"], "HANDOFF_STALE",
                 "startup approval projection differs from the audited decision")
    return current["runtime_bindings"]
