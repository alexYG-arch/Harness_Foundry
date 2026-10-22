"""Pure event projections and dependency/budget calculations.

No clock, filesystem, authorization decision or writes. The controller checks
current authority separately; readback can project expired and revoked history.
"""


def _apply_attempt_event(attempts, event, accepted=None):
    payload = event["payload"]
    kind = event["event_type"]
    if kind == "BUILD_ATTEMPT_STARTED":
        attempts[payload["attempt_id"]] = {**payload, "status": "IN_FLIGHT"}
    elif kind in {"BUILD_ATTEMPT_FINISHED", "BUILD_ATTEMPT_RECOVERED", "BUILD_ATTEMPT_RESOLVED"}:
        attempts[payload["attempt_id"]].update(payload)
        if accepted is not None:
            if payload["status"] == "ACCEPTED":
                accepted[payload["workpack_id"]] = payload
            else:
                accepted.pop(payload["workpack_id"], None)
    elif kind == "BUILD_ACCEPTANCE_INVALIDATED":
        if accepted is not None:
            for workpack_id in payload["workpack_ids"]:
                record = accepted.pop(workpack_id, None)
                if record is not None:
                    if record["attempt_id"] in attempts:
                        attempts[record["attempt_id"]].update(status="INVALIDATED", invalidation=payload)
        else:
            # Historical readback includes every previously accepted attempt;
            # execution's accepted map contains only the current task version.
            for attempt in attempts.values():
                if (attempt["prepared_event_id"] == payload["prepared_event_id"]
                        and attempt["workpack_id"] in payload["workpack_ids"] and attempt["status"] == "ACCEPTED"):
                    attempt.update(status="INVALIDATED", invalidation=payload)


def project_execution_state(events, prepared_id):
    attempts, accepted = {}, {}
    for event in events:
        if event["payload"].get("prepared_event_id") == prepared_id:
            if event["event_type"] == "BUILD_AUTHORIZATION_APPROVED":
                accepted.update(event["payload"].get("rebind", {}).get("accepted", {}))
            _apply_attempt_event(attempts, event, accepted)
    return attempts, accepted


def prepared_lineage(events, prepared_id):
    """Ordered, explicit ancestry; no implicit merging of other preparations."""
    prepared = {e["event_id"]: e["payload"] for e in events if e["event_type"] == "BUILD_AUTHORIZATION_PREPARED"}
    lineage = []
    current = prepared_id
    while current is not None:
        if current in lineage or current not in prepared:
            raise ValueError("invalid preparation ancestry")
        lineage.append(current)
        current = prepared[current].get("rebind_from")
    return list(reversed(lineage))


def project_budget_attempts(events, prepared_id):
    """Unique real attempts in the declared lineage; old statuses stay historical."""
    lineage = set(prepared_lineage(events, prepared_id))
    attempts = {}
    for event in events:
        if event["payload"].get("prepared_event_id") in lineage:
            _apply_attempt_event(attempts, event)
    return attempts


def is_checker_reverification(attempt):
    """Only the new explicit host-correction path is free of production charge.

    Historical revalidation attempts keep their original charge. The full
    history projection remains intact for recovery, feedback and artifact use.
    """
    return (attempt.get("reverify_kind") == "SAME_SCOPE_CHECKER_REVERIFY_V1"
            and attempt.get("production_budget_charge") == 0
            and bool(attempt.get("reverification_of_attempt_id")))


def production_attempts(attempts):
    return [row for row in attempts if not is_checker_reverification(row)]


def task_budget_usage(attempts):
    usage = {}
    for attempt in production_attempts(attempts):
        for owner in attempt.get("budget_workpack_ids", [attempt["workpack_id"]]):
            usage[owner] = usage.get(owner, 0) + 1
    return usage


def attempt_budget(scope, attempts):
    usage = task_budget_usage(attempts)
    charged = len(production_attempts(attempts))
    return {"attempts_consumed": charged,
            "attempts_remaining": max(0, scope["max_attempts"] - charged),
            **({"checker_reverification_rounds": len(attempts) - charged} if charged != len(attempts) else {}),
            "task_attempts_consumed": usage,
            "task_attempts_remaining": {key: max(0, scope["max_task_attempts"] - count)
                                        for key, count in usage.items()}, "reset": False}


def affected_workpacks(plan, producers):
    affected = set(producers)
    while True:
        expanded = affected | {task["workpack_id"] for task in plan["workpacks"]
                               if affected.intersection(task["depends_on"])}
        if expanded == affected:
            return affected
        affected = expanded


def repair_budget_exhaustion(prepared, attempts, required):
    """Count each required task once, including shared owners after replanning."""
    required = set(required)
    attempts = {key: row for key, row in attempts.items() if not is_checker_reverification(row)}
    scope, owners = prepared["scope"], prepared["task_budget_owners"]
    for key in sorted(required):
        for owner in owners[key]:
            spent = sum(owner in row.get("budget_workpack_ids", [row["workpack_id"]])
                        for row in attempts.values())
            needed = sum(owner in owners[item] for item in required)
            if spent + needed > scope["max_task_attempts"]:
                return {"status": "TASK_REPAIR_BUDGET_EXHAUSTED", "workpack_id": key}
    if len(attempts) + len(required) > scope["max_attempts"]:
        return {"status": "ATTEMPT_BUDGET_EXHAUSTED"}
    return None


def failure_status(result):
    if result.get("status") in {"PASS", "MODEL_TURN_COMPLETED"}:
        return None
    if (result.get("status") == "MODEL_PROCESS_FAILED"
            or result.get("status") == "VALIDATION_FAILED" and (
                result.get("automatic_retry_allowed") is False
                or result.get("model_process_started") is False
                or result.get("workload_started") is False)):
        return "BLOCKED"
    if result.get("status") == "VALIDATION_FAILED":
        return "REJECTED"
    return "UNKNOWN_SIDE_EFFECT"


def project_readback_attempts(events):
    attempts = {}
    implementation_plans = {}
    for event in events:
        payload = event["payload"]
        _apply_attempt_event(attempts, event)
        if event["event_type"] == "BUILD_ATTEMPT_STARTED":
            attempts[payload["attempt_id"]].update(implementation_commands=[], resource_commands=[])
            implementation_plans[payload["attempt_id"]] = set()
        elif event["event_type"] == "BUILD_COMMAND_REASSESSED":
            attempts[payload["attempt_id"]].setdefault("command_reassessments", []).append({
                "event_id": event["event_id"], "command_id": payload["command_id"],
                "policy": payload["policy"], "original_result": payload["original_result"],
                "result": payload["result"], "automatic_acceptance": False})
        elif event["event_type"] in {"BUILD_COMMAND_PLANNED", "BUILD_COMMAND_STARTED", "BUILD_COMMAND_OBSERVED"}:
            attempts[payload["attempt_id"]]["last_command"] = {
                "event_id": event["event_id"], "event_type": event["event_type"], **payload}
            if event["event_type"] == "BUILD_COMMAND_OBSERVED" and "resource_binding" in payload:
                attempts[payload["attempt_id"]]["resource_commands"].append({
                    "event_id": event["event_id"], "command_id": payload["command_id"],
                    "case_id": payload["case_id"], "binding": payload["resource_binding"],
                    "observation_root": payload["observation_root"],
                    "effective_network_policy": payload["result"].get("effective_network_policy"),
                    "reports": payload["result"].get("resource_reports", []),
                    "cleanup": payload["result"].get("resource_cleanup")})
            if payload["phase"] == "IMPLEMENTATION":
                if event["event_type"] == "BUILD_COMMAND_PLANNED":
                    implementation_plans[payload["attempt_id"]].add(payload["command_id"])
                elif event["event_type"] == "BUILD_COMMAND_OBSERVED":
                    attempts[payload["attempt_id"]]["implementation_commands"].append({
                        "event_id": event["event_id"], "command_id": payload["command_id"],
                        "phase": payload["phase"], "executor": payload["executor"],
                        "final_message": payload.get("result", {}).get("final_message"),
                        "observation_root": payload.get("observation_root"),
                    })
    for row in attempts.values():
        observed = {command["command_id"] for command in row["implementation_commands"]}
        missing = implementation_plans[row["attempt_id"]] - observed
        row["implementation_observation_status"] = (
            "MISSING_OBSERVATION" if missing else "OBSERVED" if observed else "NO_IMPLEMENTATION_COMMAND")
        row["missing_implementation_command_ids"] = sorted(missing)
        action = {"UNKNOWN_SIDE_EFFECT": "RECONCILE_EFFECTS", "IN_FLIGHT": "RECONCILE_COMMAND_OBSERVATIONS",
                  "BLOCKED": "REPAIR_RUNTIME_ENVIRONMENT", "REJECTED": "REPAIR_WITHIN_BUDGET",
                  "ACCEPTED": "NO_REPLAY", "RETRY_ALLOWED": "ADVANCE_WITH_CURRENT_SCOPE_AND_BUDGET",
                  "NOT_DISPATCHED": "ADVANCE_WITH_CURRENT_SCOPE_AND_BUDGET",
                  "INVALIDATED": "REBUILD_AFFECTED_BRANCH_WITHIN_BUDGET"}.get(row["status"], "INSPECT")
        row["recovery"] = {"next_action": action, "automatic_acceptance": False}
        command = row.get("last_command", {})
        row["phase"] = command.get("phase", "NOT_DISPATCHED")
        row["recovery"].update(owner="LOCAL_OPERATOR" if row["status"] in {"UNKNOWN_SIDE_EFFECT", "BLOCKED"}
                               else "BUILD_CONTROLLER", evidence_attempt_id=row["attempt_id"],
                               minimum_return_path=action)
        if row["status"] == "REJECTED" and failure_status(command.get("result", {})) == "BLOCKED":
            row["recovery"].update(next_action="REPAIR_RUNTIME_ENVIRONMENT", historical_classification="REJECTED")
        if row["status"] in {"BLOCKED", "REJECTED"} and any(
                check.get("result", {}).get("failure_domain") == "ACCEPTANCE_CONTRACT_GAP"
                for check in row.get("verification", [])):
            row["recovery"]["next_action"] = "ALIGN_PUBLIC_CONTRACT_AND_VERIFIER"
        row["recovery"]["minimum_return_path"] = row["recovery"]["next_action"]
    return attempts
