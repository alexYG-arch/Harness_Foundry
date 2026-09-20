"""Native observation provenance for Workpack consumers.

Inputs must be events from the caller's verified Program-local controller.
Historical evidence is not current execution authority. No files, processes,
capabilities, acceptance receipts or successor transitions are created here.
"""

from .control_kernel import START_PACKAGE_BINDING_KIND, rebuild_control_projections
from .models import content_sha256


def committed_native_attempts(events, program_id, candidate_tree_sha256):
    """Select observed and committed attempts from an approved native Parent."""
    projection = rebuild_control_projections(events)["grant_ledger"]
    observations = {event["payload"]["grant_id"]: event for event in events
                    if event["event_type"] == "COMMAND_RESULT_OBSERVED"}
    for event in events:
        if event["event_type"] != "TRANSITION_COMMITTED":
            continue
        row = event["payload"]
        grant = projection["derived_grants"].get(row.get("grant_id"), {})
        parent = projection["parents"].get(grant.get("parent_authorization_id"), {})
        binding = parent.get("bindings", {})
        observed = observations.get(row.get("grant_id"))
        if (parent.get("program_id") != program_id or not parent.get("approval_receipt_sha256")
                or binding.get("binding_kind") != START_PACKAGE_BINDING_KIND
                or binding.get("candidate_tree_sha256") != candidate_tree_sha256
                or not observed or observed["payload"].get("result") != row.get("result")
                or any(observed["payload"].get(key) != row.get(key) for key in ("attempt_id", "transition_id"))
                or grant.get("attempt_id") != row.get("attempt_id")
                or row.get("result", {}).get("status") != "PASS"):
            continue
        for kind, command_class in (("startup_execution", "CANDIDATE_NATIVE_REGISTRATION"),
                                    ("coding_execution", "CODEX_CODING_MODEL_TURN"),
                                    ("local_execution", "LOCAL_OFFLINE_PROCESS")):
            transition = parent.get(kind, {}).get("transitions", {}).get(row["transition_id"], {})
            if (not transition or grant.get("transition_contract_sha256") != content_sha256(transition)
                    or transition.get("command_contract", {}).get("command_class") != command_class):
                continue
            yield {"kind": kind, "parent": parent, "grant": grant, "transition": transition,
                   "commit": event, "observation": observed, "result": row["result"]}


def predecessor_capability_observations(events, plan):
    """Resolve declared startup capability sources, never a same-named file.

Workpack-produced capability acceptance is a separate provider not implemented
by this reader. Keep those requirements explicit instead of inferring them from
a completed coding/verification command or an agent-written result.
"""
    attempts = list(committed_native_attempts(events, plan["program_id"], plan["candidate_tree_sha256"]))
    rows = []
    for capability in plan["required_capabilities"]:
        source = plan["capability_sources"].get(capability)
        supported = isinstance(source, str) and source in {
            "ENGINEERING_DAG:SHARED_CONTROL_BASELINE_LOCK", "ENGINEERING_DAG:CONTROL_PLANE_REGISTRATION",
            "ENGINEERING_DAG:PROGRAM_DRIVER_RUNTIME_VERIFIED"}
        matches = []
        if supported:
            node = source.split(":", 1)[1]
            for attempt in attempts:
                transaction = attempt["result"].get("native_transaction", {})
                native = transaction.get("result_payload", {})
                if (attempt["kind"] != "startup_execution" or attempt["transition"]["transition_id"] != node
                        or transaction.get("candidate_tree_sha256") != plan["candidate_tree_sha256"]
                        or native.get("program_id") != plan["program_id"] or native.get("node_id") != node
                        or native.get("status") != "PASS" or native.get("authorization_id") != attempt["grant"]["grant_id"]
                        or capability not in native.get("produced_capabilities", [])):
                    continue
                matches.append({"grant_id": attempt["grant"]["grant_id"],
                    "observation_event_hash": attempt["observation"]["event_hash"],
                    "commit_event_hash": attempt["commit"]["event_hash"],
                    "evidence_ref": attempt["result"]["artifact_id"],
                    "evidence_scope": "COMMITTED_STARTUP_CAPABILITY_ONLY"})
        rows.append({"capability": capability, "source": source,
                     "status": "OBSERVED" if matches else "MISSING" if supported else "PROVIDER_NOT_IMPLEMENTED",
                     "observations": matches})
    return rows


def latest_native_command_grant(events, plan, native_command):
    """A started but failed/pending newer check cannot revive an older PASS."""
    projection = rebuild_control_projections(events)["grant_ledger"]
    grants = {value["grant_id"]: value for value in projection["derived_grants"].values()}
    latest = None
    for event in events:
        if event["event_type"] != "TRANSITION_ATTEMPT_STARTED":
            continue
        row = event["payload"]
        grant = grants.get(row.get("grant_id"), {})
        parent = projection["parents"].get(grant.get("parent_authorization_id"), {})
        binding = parent.get("bindings", {})
        transition = parent.get("local_execution", {}).get("transitions", {}).get(row["transition_id"], {})
        invocation = transition.get("command_contract", {}).get("local_invocation", {})
        if (parent.get("program_id") == plan["program_id"] and parent.get("approval_receipt_sha256")
                and binding.get("binding_kind") == START_PACKAGE_BINDING_KIND
                and binding.get("candidate_tree_sha256") == plan["candidate_tree_sha256"]
                and grant.get("attempt_id") == row.get("attempt_id")
                and grant.get("transition_contract_sha256") == content_sha256(transition)
                and invocation.get("native_command") == native_command
                and invocation.get("project_id") == plan["project_id"] and invocation.get("workpack_id") == plan["workpack_id"]):
            latest = grant["grant_id"]
    return latest
