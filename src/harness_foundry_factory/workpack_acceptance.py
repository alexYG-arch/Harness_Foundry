"""Read-only Workpack completion planning and evidence audit.

Command completion and JSON Schema checks are implemented here. They are not
independent semantic Oracles or Workpack acceptance. Unsupported obligations
remain visible and unresolved; this module cannot grant a capability, write an
acceptance receipt, execute a verifier, or select a successor.
"""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from collections.abc import Mapping

from .control_kernel import ControlKernelError, START_PACKAGE_BINDING_KIND, rebuild_control_projections
from .local_runtime import _uri
from .models import FactoryError, content_sha256
from .store import ControlEventStore
from .workpack_runtime import RuntimeContractError, candidate_identity, plan_workpack_node


def _require(condition, message):
    if not condition:
        raise RuntimeContractError("WORKPACK_COMPLETION_PLAN_INVALID", message)


def _resource(ref):
    try:
        return _uri(ref)
    except ControlKernelError as exc:
        raise RuntimeContractError("WORKPACK_COMPLETION_PLAN_INVALID", str(exc)) from exc


def plan_workpack_completion(candidate_root, node_id, workpack_id):
    """Retain the complete native unit, not just its structural result schema."""
    node = plan_workpack_node(Path(candidate_root), node_id)
    units = node["units"]
    matches = [unit for unit in units if unit["workpack_id"] == workpack_id]
    _require(len(matches) == 1, "select exactly one Workpack owned by the node")
    unit = matches[0]
    bundle = unit["task_bundle"]
    artifacts = []
    if bundle is not None:
        contracts = bundle.get("task_contracts")
        _require(isinstance(contracts, list) and bool(contracts), "task contracts are missing")
        for task in contracts:
            _require(isinstance(task, Mapping) and task.get("workpack_id") == workpack_id
                     and isinstance(task.get("artifact_obligations"), list), "task contract ownership differs")
            for artifact in task["artifact_obligations"]:
                _require(isinstance(artifact, Mapping) and all(key in artifact for key in (
                    "artifact_id", "artifact_ref", "schema", "validation_rule", "oracle", "failure_return")),
                    "complete artifact schema, validation, Oracle and failure return are required")
                _resource(artifact["artifact_ref"])
                artifacts.append(deepcopy(artifact))
        ids = [item["artifact_id"] for item in artifacts]
        refs = [item["artifact_ref"] for item in artifacts]
        _require(len(ids) == len(set(ids)) and len(refs) == len(set(refs))
                 and ids == bundle.get("required_artifact_ids")
                 and refs == bundle.get("required_artifact_refs")
                 and ids == unit["workpack"].get("required_artifact_ids")
                 and refs == unit["workpack"].get("required_artifact_refs"),
                 "artifact obligations must equal the complete ordered Workpack set")
    workpack = unit["workpack"]
    return {
        "status": "DECLARED_WORKPACK_COMPLETION_PLAN",
        "program_id": node["program_id"], "candidate_tree_sha256": node["candidate_tree_sha256"],
        "node_id": node_id, "project_id": unit["project_id"], "workpack_id": workpack_id,
        "required_predecessor_nodes": deepcopy(node["required_predecessor_nodes"]),
        "required_prior_workpacks": [item["workpack_id"] for item in units[:units.index(unit)]],
        "required_capabilities": deepcopy(workpack.get("requires", [])),
        "capability_sources": deepcopy(workpack.get("requirement_sources", {})),
        "declared_produced_capabilities": deepcopy(workpack.get("produces", [])),
        "command_execution_order": deepcopy(workpack["command_execution_order"]),
        "unit": deepcopy(unit), "artifacts": artifacts,
        # Preserve extensions (e.g. the Lab protocol/CLI contract) rather than
        # assuming that validating the artifact array covers every obligation.
        "semantic_contract": deepcopy(bundle),
        "workpack_success_rule": workpack.get("success_rule"),
        "failure_return_node": workpack.get("failure_return_node"),
        "source_refs": deepcopy(node["source_refs"]),
        "optional_schema_audit_dependencies": ["jsonschema>=4.18,<5", "referencing>=0.28,<1"],
        "execution_authorized": False, "workpack_accepted": False, "writes_performed": False,
    }


def _read_events(database, program):
    if not database.exists():
        return [], "CONTROLLER_ABSENT"
    # A mode=ro WAL connection can create/update sidecars in the source root.
    # This non-authoritative diagnostic instead reads a disposable copy of the
    # database AND its WAL. Never mark a live source immutable or drop its WAL.
    sources = [database, Path(str(database) + "-wal")]

    def signatures():
        result = {}
        for path in sources:
            _require(path.resolve() == path, "controller sidecar is linked")
            try:
                stat = path.stat()
                result[path] = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
            except FileNotFoundError:
                result[path] = None
        return result

    try:
        before = signatures()
        with tempfile.TemporaryDirectory(prefix="foundry-read-audit-") as directory:
            copied = Path(directory) / database.name
            for path, signature in before.items():
                if signature is not None:
                    shutil.copyfile(path, Path(directory) / path.name)
            _require(before == signatures(), "controller changed while copying; repeat the diagnostic at a stable point")
            store = ControlEventStore(copied, read_only=True)
            _require(store.verify_stream(program)["status"] == "PASS", "copied control stream is invalid")
            programs = set(store.list_program_ids())
            _require(programs.issubset({program}), "controller belongs to another Program")
            if not programs:
                return [], "CONTROLLER_EMPTY_COPY"
            return store.list_events(program), "STABLE_FILESET_DIAGNOSTIC_COPY"
    except (OSError, sqlite3.Error, FactoryError) as exc:
        raise RuntimeContractError("WORKPACK_CONTROL_AUDIT_UNAVAILABLE", str(exc)) from exc


def _command_observations(events, plan):
    """Use observed + committed native attempts, never result files/stdout PASS."""
    projections = rebuild_control_projections(events)
    parents = projections["grant_ledger"]["parents"]
    grants = projections["grant_ledger"]["derived_grants"]
    observations = {event["payload"]["grant_id"]: event for event in events
                    if event["event_type"] == "COMMAND_RESULT_OBSERVED"}
    expected = {command["command_id"]: command for command in plan["unit"]["commands"]}
    results = {key: [] for key in expected}
    for event in events:
        if event["event_type"] != "TRANSITION_COMMITTED":
            continue
        row = event["payload"]
        grant = grants.get(row.get("grant_id"), {})
        parent = parents.get(grant.get("parent_authorization_id"), {})
        if (not parent.get("approval_receipt_sha256")
                or parent.get("bindings", {}).get("binding_kind") != START_PACKAGE_BINDING_KIND
                or parent["bindings"].get("candidate_tree_sha256") != plan["candidate_tree_sha256"]):
            continue
        for key in ("coding_execution", "local_execution"):
            transition = parent.get(key, {}).get("transitions", {}).get(row["transition_id"], {})
            if not transition or grant.get("transition_contract_sha256") != content_sha256(transition):
                continue
            invocation = transition["command_contract"].get(
                "coding_invocation" if key == "coding_execution" else "local_invocation", {})
            task = invocation.get("task_input", {}) if key == "coding_execution" else invocation
            selected = task.get("selection", task)
            native = task.get("native_command", {})
            command_id = native.get("command_id")
            if (selected.get("workpack_id") != plan["workpack_id"]
                    or selected.get("project_id") != plan["project_id"]
                    or expected.get(command_id) != native):
                continue
            if key == "coding_execution" and any(task.get(field) != plan["unit"][field]
                    for field in ("workpack", "capsule", "task_bundle")):
                continue
            observation = observations.get(row.get("grant_id"))
            if not observation or observation["payload"].get("result") != row.get("result"):
                continue
            result = row["result"]
            if result.get("status") != "PASS":
                continue
            coding = key == "coding_execution"
            process = result.get("model_result" if coding else "process_result", {})
            complete = (process.get("status") == "MODEL_TURN_COMPLETED" if coding else
                        process.get("exit_code") == 0 and process.get("timed_out") is False
                        and process.get("workload_started") is not False)
            if complete:
                results[command_id].append({"grant_id": grant["grant_id"],
                    "attempt_id": row["attempt_id"], "observation_event_hash": observation["event_hash"],
                    "commit_event_hash": event["event_hash"], "job_id": selected.get("job_id"),
                    "evidence_scope": "MODEL_TURN_ONLY" if coding else "PROCESS_EXIT_ONLY"})
    # These are historical observations for this Candidate. Parent expiry or
    # revocation does not erase them, and they do not grant current authority.
    return [{"command_id": key, "status": "OBSERVED" if results[key] else "MISSING",
             "observations": results[key]} for key in plan["command_execution_order"]]


def _schema_observation(candidate, execution, artifact):
    ref = artifact["artifact_ref"]
    domain, parts = _resource(ref)
    base = {"artifact_id": artifact["artifact_id"], "artifact_ref": ref,
            "semantic_validation": "NOT_EVALUATED", "oracle": "NOT_EVALUATED"}
    if domain == "execution" and parts[:1] == ("jobs",):
        # Inspection is not a lease. A later authority-bound reader must supply
        # these bytes under the existing Job protocol, not an audit-root bypass.
        return {**base, "schema": "NOT_READ", "reason_code": "JOB_READ_LEASE_REQUIRED"}
    if domain not in {"candidate", "execution"}:
        return {**base, "schema": "NOT_READ", "reason_code": "ARTIFACT_DOMAIN_UNSUPPORTED"}
    root = candidate if domain == "candidate" else execution
    path = root.joinpath(*parts)
    _require(path.resolve() == path and path.is_relative_to(root), "artifact path is linked outside its binding")
    if not path.is_file():
        return {**base, "schema": "MISSING", "reason_code": "ARTIFACT_MISSING"}
    try:
        value = json.loads(path.read_bytes())
    except (ValueError, UnicodeError):
        return {**base, "schema": "NOT_EVALUATED", "reason_code": "JSON_ARTIFACT_REPRESENTATION_REQUIRED"}
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry
        from referencing.exceptions import NoSuchResource
    except ImportError:
        return {**base, "schema": "NOT_EVALUATED", "reason_code": "JSON_SCHEMA_DEPENDENCY_UNAVAILABLE"}

    def no_external_resource(uri):
        # External schema retrieval is neither authorized nor needed by this
        # observer. Internal JSON pointers remain supported by the library.
        raise NoSuchResource(ref=uri)

    schema = artifact["schema"]
    if isinstance(schema, Mapping) and schema.get("$schema") not in {
        None, "https://json-schema.org/draft/2020-12/schema"}:
        return {**base, "schema": "NOT_EVALUATED", "reason_code": "JSON_SCHEMA_DIALECT_UNSUPPORTED"}
    try:
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, registry=Registry(retrieve=no_external_resource))
        failures = list(validator.iter_errors(value))
    except Exception as exc:
        # A malformed/unresolvable contract is inconclusive, not a successful
        # negative test and not permission to dispatch a fallback verifier.
        return {**base, "schema": "NOT_EVALUATED", "reason_code": "JSON_SCHEMA_CONTRACT_UNRESOLVED",
                "diagnostic": str(exc)}
    return {**base, "schema": "FAIL" if failures else "PASS",
            "reason_code": "JSON_SCHEMA_REJECTED" if failures else "JSON_SCHEMA_ONLY_PASS",
            "errors": [{"instance_path": list(error.absolute_path), "schema_path": list(error.absolute_schema_path),
                        "message": error.message} for error in failures]}


def audit_workpack_completion(candidate_root, execution_root, node_id, workpack_id):
    """Inspect exact completion gaps without mutating or accepting the Workpack.

This interface has no caller-supplied result, provider, grant or acceptance
override. External semantic verifiers are not yet integrated, so its result
intentionally cannot be used to advance the runtime.
"""
    candidate, execution = Path(candidate_root), Path(execution_root)
    _require(candidate.is_absolute() and execution.is_absolute()
             and candidate.resolve() == candidate and execution.resolve() == execution
             and not execution.is_relative_to(candidate) and not candidate.is_relative_to(execution),
             "Candidate and execution must be canonical disjoint absolute roots")
    plan = plan_workpack_completion(candidate, node_id, workpack_id)
    database = execution / ".harness-foundry/control.sqlite3"
    _require(database.resolve() == database, "controller path is linked")
    events, controller_status = _read_events(database, plan["program_id"])
    commands = _command_observations(events, plan)
    artifacts = [_schema_observation(candidate, execution, item) for item in plan["artifacts"]]
    unresolved = ["INDEPENDENT_WORKPACK_VERIFIER_NOT_IMPLEMENTED"]
    if plan["semantic_contract"] is None:
        unresolved.append("NATIVE_SEMANTIC_TASK_BUNDLE_MISSING")
    if any(item["status"] != "OBSERVED" for item in commands):
        unresolved.append("NATIVE_COMMAND_OBSERVATIONS_MISSING")
    if any(item["schema"] != "PASS" for item in artifacts):
        unresolved.append("ARTIFACT_SCHEMA_EVIDENCE_INCOMPLETE")
    _require(candidate_identity(candidate) == plan["candidate_tree_sha256"], "Candidate changed during audit")
    return {"status": "WORKPACK_EVIDENCE_INCOMPLETE", "plan": plan,
        "controller_status": controller_status, "command_observations": commands,
        "artifact_observations": artifacts, "unresolved_requirements": unresolved,
        "remaining_semantic_scope": {"predecessor_nodes": plan["required_predecessor_nodes"],
            "prior_workpacks": plan["required_prior_workpacks"], "capabilities": plan["required_capabilities"],
            "task_contract": plan["semantic_contract"], "workpack_success_rule": plan["workpack_success_rule"],
            "failure_return_node": plan["failure_return_node"]},
        "workpack_accepted": False, "produced_capabilities": [], "successor_started": False,
        "execution_authorized": False, "candidate_writes_performed": False,
        "execution_writes_performed": False, "controller_events_written": False,
        "temporary_snapshot_used": controller_status != "CONTROLLER_ABSENT"}
