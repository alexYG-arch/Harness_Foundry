"""Trusted-host correction inside an existing grant, using the same event stream.

These receipts record a host's evidenced semantic review, not model authority.
JSON cannot prove semantic equivalence or authenticate the host. Workers must
not have write access to the controller database or these host entrypoints.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from .build_artifacts import file_identity, relative_path
from .build_rebind import (_event, _production_signature, approval_rebind,
                           superseding_prepared)
from .build_state import project_budget_attempts, project_execution_state
from .build_types import (IdempotencyConflictError, RequestValidationError,
                          RevisionConflictError)
from .process_observation import CommandObservation

POLICY = "SAME_SCOPE_CHECKER_CORRECTION_V1"
REVERIFY_KIND = "SAME_SCOPE_CHECKER_REVERIFY_V1"
TECHNICAL_POLICY = "HOST_TECHNICAL_DISPOSITION_V1"


def require(condition, message):
    if not condition:
        raise RequestValidationError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _utc(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    require(parsed.tzinfo is not None, "authorization time requires an absolute timezone")
    return parsed.astimezone(timezone.utc)


def validate_authority_chain(events, prepared_id, now):
    """Check approval dependencies, independently of execution supersession.

    Only automatic grants inherit revocation. A fresh human approval terminates
    this walk even if its preparation carries a budget rebind_from relation.
    """
    seen = set()
    current = prepared_id
    approvals = []
    while current is not None:
        require(current not in seen, "cyclic derived authorization")
        seen.add(current)
        prepared = _event(events, current, "BUILD_AUTHORIZATION_PREPARED")
        matches = [e for e in events if e["event_type"] == "BUILD_AUTHORIZATION_APPROVED"
                   and e["payload"].get("prepared_event_id") == current]
        require(bool(matches), "build authorization is absent")
        approval = matches[-1]
        require(not any(e["event_type"] == "BUILD_AUTHORIZATION_REVOKED"
                        and e["payload"].get("prepared_event_id") == current for e in events),
                "build authorization or its source approval was revoked")
        require(_utc(now) < _utc(prepared["payload"]["scope"]["expires_at"]),
                "build authorization or its source approval expired")
        approvals.append(approval["event_id"])
        basis = approval["payload"].get("derived_authority")
        if basis is None:
            require(_text(approval["payload"].get("human_message_ref")),
                    "authorization chain has no actual human approval")
            break
        require(isinstance(basis, dict) and set(basis) == {
                    "policy", "source_prepared_event_id", "source_approval_event_id"}
                and basis["policy"] == POLICY, "unknown derived authorization basis")
        parent = _event(events, basis["source_approval_event_id"], "BUILD_AUTHORIZATION_APPROVED")
        require(parent["payload"].get("prepared_event_id") == basis["source_prepared_event_id"]
                and parent["stream_revision"] < approval["stream_revision"],
                "derived authorization source differs")
        current = basis["source_prepared_event_id"]
    return approvals


def _host_review(review, *, policy):
    require(isinstance(review, dict) and set(review) == {
                "policy", "actor", "reason", "evidence_refs", "decision"}
            and review["policy"] == policy, "explicit trusted-host correction review required")
    actor = review["actor"]
    require(isinstance(actor, dict) and set(actor) == {"type", "chat_thread_id", "turn_id"}
            and actor["type"] == "TRUSTED_CODEX_HOST"
            and all(_text(actor[k]) for k in ("chat_thread_id", "turn_id")),
            "technical review must identify the trusted host, not a human or target worker")
    require(_text(review["reason"]) and isinstance(review["evidence_refs"], list)
            and review["evidence_refs"] and all(_text(v) for v in review["evidence_refs"]),
            "technical review requires specific reason and evidence")
    require(review["decision"] == ("EQUIVALENT_CHECKER_CORRECTION" if policy == POLICY
                                    else "TECHNICAL_FALSE_BLOCK_CONFIRMED"),
            "host review does not authorize this technical correction")


def _capture(command):
    """Require complete bound process evidence; do not infer from PID absence."""
    root = Path(command["observation_root"])
    require(all((root / n).is_file() and not (root / n).is_symlink()
                for n in ("binding.json", "capture.json", "result.json")),
            "complete durable command capture is required")
    capture = json.loads((root / "capture.json").read_text())
    require(type(capture.get("exit_code")) is int and capture.get("timed_out") is False
            and not capture.get("capture_error") and not capture.get("cancellation_reason"),
            "command termination is not established")
    require(isinstance(capture.get("stream_bytes"), dict), "capture stream lengths are missing")
    for name in ("stdout", "stderr"):
        path = root / (name + ".bin")
        require(type(capture["stream_bytes"].get(name)) is int
                and capture["stream_bytes"][name] == (path.stat().st_size if path.is_file() else 0)
                and not path.is_symlink(), "command stream capture is incomplete")
    if command["executor"] == "CODEX":
        require((root / "model-configuration.json").is_file(),
                "completed model implementation requires its original configuration receipt")
    result = CommandObservation.recover(root, command["command_id"], command["executor"])
    captured_result = result.get("capture", result)
    require(all(captured_result.get(k) == v for k, v in capture.items()),
            "completion receipt differs from the original process capture")
    if "resource_binding" in command:
        from .build_reconciliation import _completed_resource_result
        result = _completed_resource_result(command)
        require(result is not None and result.get("resource_cleanup", {}).get("status") in {"CLEANED", "RETAINED", "CLEANUP_WARNING"},
                "resource settlement and cleanup must be complete")
    elif command["phase"] == "VERIFICATION":
        from .build_runtime import classify_verification_result
        result = classify_verification_result(result)
    require(result == command["result"], "durable capture differs from the recorded command result")
    return result


def _completed_commands(events, attempt):
    rows = [e for e in events if e["payload"].get("attempt_id") == attempt["attempt_id"]]
    intents = [e["payload"] for e in rows if e["event_type"] == "BUILD_COMMAND_PLANNED"]
    facts = [e["payload"] for e in rows if e["event_type"] == "BUILD_COMMAND_OBSERVED"]
    require(intents and len(intents) == len(facts)
            and len({c["command_id"] for c in intents}) == len(intents)
            and len({c["command_id"] for c in facts}) == len(facts),
            "every command requires exactly one complete observation")
    for intent, fact in zip(intents, facts):
        require(all(fact.get(k) == v for k, v in intent.items())
                and all(intent.get(k) == attempt.get(k) for k in
                        ("attempt_id", "prepared_event_id", "proposal_event_id", "workpack_id", "job_id")),
                "command or attempt binding differs")
        result = _capture(fact)
        if fact["executor"] == "CODEX":
            prepared = _event(events, attempt["prepared_event_id"], "BUILD_AUTHORIZATION_PREPARED")["payload"]
            scope = prepared["scope"]
            config = result["model_configuration"]
            require(config.get("model_policy") == scope.get("model_policy", "FIXED")
                    and config.get("model_service") == scope.get("model_service", {"provider":"openai", "config":{}}),
                    "original model configuration differs from its approved policy/service")
            if scope.get("model_policy", "FIXED") == "FIXED":
                require(config.get("model") == scope.get("model")
                        and config.get("model_reasoning_effort") == scope.get("model_reasoning_effort"),
                        "original fixed model selection differs from its approval")
    starts = [e["payload"] for e in rows if e["event_type"] == "BUILD_COMMAND_STARTED"]
    require(len({c["command_id"] for c in starts}) == len(starts), "duplicate command starts")
    for start in starts:
        intent = next((c for c in intents if c["command_id"] == start["command_id"]), None)
        require(intent is not None and all(start.get(k) == v for k, v in intent.items()),
                "unbound process start requires ordinary reconciliation")
    return facts


def _effects_review(receipt, command_ids):
    require(isinstance(receipt, dict) and set(receipt) == {
                "status", "command_ids", "detail", "evidence_refs"}
            and receipt["status"] == "EFFECTS_RECONCILED"
            and isinstance(receipt["command_ids"], list)
            and len(receipt["command_ids"]) == len(set(receipt["command_ids"]))
            and set(receipt["command_ids"]) == set(command_ids)
            and _text(receipt["detail"]) and isinstance(receipt["evidence_refs"], list)
            and receipt["evidence_refs"] and all(_text(v) for v in receipt["evidence_refs"]),
            "the host must reconcile all command effects from specific evidence")


def completed_implementation_candidates(events, previous_id, receipts):
    """Qualify explicitly reviewed, completed but unaccepted producers only."""
    require(isinstance(receipts, dict), "completed attempt reviews must be an object")
    history = project_budget_attempts(events, previous_id)
    _, accepted = project_execution_state(events, previous_id)
    require(not any(a["status"] in {"IN_FLIGHT", "UNKNOWN_SIDE_EFFECT"} for a in history.values()),
            "unresolved attempts require ordinary reconciliation")
    candidates = {}
    for attempt_id, receipt in receipts.items():
        attempt = history.get(attempt_id)
        require(attempt is not None and attempt["status"] in {"BLOCKED", "REJECTED"}
                and not attempt.get("reverification_of_attempt_id"),
                "only completed unaccepted production can use this qualification")
        latest = [a for a in history.values() if a["workpack_id"] == attempt["workpack_id"]][-1]
        require(latest["attempt_id"] == attempt_id and attempt["workpack_id"] not in accepted,
                "a later attempt or accepted version supersedes this producer")
        require(isinstance(receipt, dict) and set(receipt) == {"artifacts", "effects"},
                "completed producer review requires its artifacts and effects")
        commands = _completed_commands(events, attempt)
        implementations = [c for c in commands if c["phase"] == "IMPLEMENTATION"]
        require(len(implementations) == 1 and implementations[0]["result"].get("status") in {"PASS", "MODEL_TURN_COMPLETED"},
                "the original implementation did not complete successfully")
        require(all(c["result"].get("status") == "PASS" for c in commands if c["phase"] == "PREFLIGHT"),
                "original environment preflight failed")
        checks = [c for c in commands if c["phase"] == "VERIFICATION"]
        require(checks, "an actual checker failure is required")
        require(attempt.get("effects", {}).get("status") not in {"VIOLATION", "NOT_OBSERVED", "MISSING_REQUIRED"},
                "original effects are not reconciled")
        _effects_review(receipt["effects"], [c["command_id"] for c in commands])
        inputs = [e["payload"] for e in events if e["event_type"] == "BUILD_VERIFICATION_INPUTS"
                  and e["payload"].get("attempt_id") == attempt_id]
        require(len(inputs) == 1 and inputs[0]["artifacts"] == attempt.get("artifacts") == receipt["artifacts"]
                and bool(receipt["artifacts"]), "original product version is not fully bound")
        prepared = _event(events, attempt["prepared_event_id"], "BUILD_AUTHORIZATION_PREPARED")["payload"]
        proposal = _event(events, attempt["proposal_event_id"], "BUILD_PLAN_PROPOSED")["payload"]
        task = next(t for t in proposal["plan"]["workpacks"] if t["workpack_id"] == attempt["workpack_id"])
        start_index = next(i for i,e in enumerate(events) if e["event_type"] == "BUILD_ATTEMPT_STARTED"
                           and e["payload"].get("attempt_id") == attempt_id)
        prior_accepted = project_execution_state(events[:start_index], attempt["prepared_event_id"])[1]
        require(all(dep in prior_accepted and dep in accepted
                    and prior_accepted[dep]["artifacts"] == accepted[dep]["artifacts"] for dep in task["depends_on"]),
                "upstream accepted input version changed")
        workspace = Path(prepared["scope"]["workspace_root"])
        for item in receipt["artifacts"].values():
            require(file_identity(relative_path(workspace, item["path"])) == {k:item[k] for k in ("sha256","size")},
                    "unaccepted product bytes changed")
        candidate = deepcopy(attempt)
        candidate["unaccepted_completed_implementation"] = True
        candidates[attempt["workpack_id"]] = candidate
    return candidates


def _same_scope(events, previous, prepared, proposal):
    old_proposal = _event(events, previous["proposal_event_id"], "BUILD_PLAN_PROPOSED")["payload"]
    require(proposal["requirement_ir"] == old_proposal["requirement_ir"]
            and proposal["document_review"] == old_proposal["document_review"]
            and prepared["acceptance_contracts"] == previous["acceptance_contracts"],
            "public requirements, expected outcomes or human review changed")
    old_scope, new_scope = deepcopy(previous["scope"]), deepcopy(prepared["scope"])
    old_scope.pop("verification_root"); new_scope.pop("verification_root")
    for scope in (old_scope, new_scope):
        if "verification_resources" in scope:
            # Declared helper files are copied into the same protected root;
            # their list is not a new host read/write or network capability.
            scope["verification_resources"].pop("checker_files", None)
    require(old_scope == new_scope, "same-scope correction cannot change execution, resources, budgets or expiry")
    old_source = _event(events, previous["source_event_id"], "BUILD_SOURCES_CAPTURED")["payload"]
    new_source = _event(events, prepared["source_event_id"], "BUILD_SOURCES_CAPTURED")["payload"]
    require(all(old_source[k] == new_source[k] for k in ("source_root", "manifest", "snapshot")),
            "correction cannot replace original requirement sources")
    before = {t["workpack_id"]: t for t in old_proposal["plan"]["workpacks"]}
    after = {t["workpack_id"]: t for t in proposal["plan"]["workpacks"]}
    require(before.keys() == after.keys(), "same-scope correction keeps task identities")
    for key in before:
        require(_production_signature(events, old_proposal, previous, before[key]) ==
                _production_signature(events, proposal, prepared, after[key]),
                "same-scope correction cannot change production or its input semantics")
        old_cases = {c["case_id"]:{k:v for k,v in c.items() if k != "argv"} for c in before[key]["verification"]}
        new_cases = {c["case_id"]:{k:v for k,v in c.items() if k != "argv"} for c in after[key]["verification"]}
        require(old_cases == new_cases, "correction cannot remove or replace independent assertions")


def derive_checker_authorization(store, program_id, prepared_id, *, evidence,
                                 expected_revision, idempotency_key, created_at):
    request = {"prepared_event_id":prepared_id,"evidence":evidence,"expected_revision":expected_revision}
    replay = store.idempotent_events(program_id, idempotency_key)
    if replay is not None:
        require(len(replay) == 1 and replay[0]["event_type"] == "BUILD_AUTHORIZATION_APPROVED", "invalid correction replay")
        if replay[0]["payload"].get("correction_request") != request:
            raise IdempotencyConflictError("correction key reused with different content")
        return replay[0]
    events = store.list_events(program_id)
    if len(events) != expected_revision:
        raise RevisionConflictError("re-read current scope before correction")
    prepared_event = _event(events, prepared_id, "BUILD_AUTHORIZATION_PREPARED")
    prepared = prepared_event["payload"]
    previous_id = prepared.get("rebind_from")
    require(previous_id is not None, "same-scope correction requires an explicit prior binding")
    validate_authority_chain(events, previous_id, created_at)
    require(superseding_prepared(events, previous_id) is None
            and not any(e["event_type"] in {"BUILD_AUTHORIZATION_APPROVED", "BUILD_AUTHORIZATION_REVOKED"}
                        and e["payload"].get("prepared_event_id") == prepared_id for e in events),
            "correction binding is already approved, revoked or superseded")
    previous = _event(events, previous_id, "BUILD_AUTHORIZATION_PREPARED")["payload"]
    proposal_event = _event(events, prepared["proposal_event_id"], "BUILD_PLAN_PROPOSED")
    require(proposal_event == [e for e in events if e["event_type"] == "BUILD_PLAN_PROPOSED"][-1],
            "correction proposal is no longer current")
    require(_utc(prepared_event["created_at"]) <= _utc(created_at) < _utc(prepared["scope"]["expires_at"]),
            "correction must follow preparation within original validity")
    _same_scope(events, previous, prepared, proposal_event["payload"])
    require(isinstance(evidence, dict) and set(evidence) == {
                "review", "source_prepared_event_id", "old_verifier_files", "new_verifier_files",
                "preserved_case_ids", "changed_files", "completed_attempts"}, "bind exact old/new checkers and original assertion review")
    _host_review(evidence["review"], policy=POLICY)
    require(evidence["source_prepared_event_id"] == previous_id
            and evidence["old_verifier_files"] == previous["verifier_files"]
            and evidence["new_verifier_files"] == prepared["verifier_files"], "checker review version differs")
    cases = [c["case_id"] for t in proposal_event["payload"]["plan"]["workpacks"] for c in t["verification"]]
    require(isinstance(evidence["preserved_case_ids"], list)
            and sorted(evidence["preserved_case_ids"]) == sorted(cases), "every original independent assertion must be reviewed")
    changes = {name for name in previous["verifier_files"].keys() | prepared["verifier_files"].keys()
               if previous["verifier_files"].get(name) != prepared["verifier_files"].get(name)}
    require(isinstance(evidence["changed_files"], dict) and set(evidence["changed_files"]) == changes,
            "review every changed checker file, including declared helpers")
    for detail in evidence["changed_files"].values():
        require(isinstance(detail, dict) and set(detail) == {"role", "reason"}
                and detail["role"] == "CHECKER_ADAPTER" and _text(detail["reason"]),
                "changed expectations or assertions require a real scope decision")
    # checker_files contains code and helpers as well as expectations. Do not
    # reject a legitimate adapter fix merely because it is a declared dependency.
    # The host must review the actual diff; file roles alone prove no equivalence.
    for binding in (previous, prepared):
        for name, identity in binding["verifier_files"].items():
            require(file_identity(relative_path(Path(binding["scope"]["verification_root"]), name)) == identity,
                    "old or corrected checker bytes changed after preparation")
    candidates = completed_implementation_candidates(events, previous_id, evidence["completed_attempts"])
    rebind = approval_rebind(events, previous_id, prepared, proposal_event["payload"], extra_candidates=candidates)
    for record in rebind["verification_pending"].values():
        record.update(reverify_kind=REVERIFY_KIND, production_budget_charge=0)
    source = [e for e in events if e["event_type"] == "BUILD_AUTHORIZATION_APPROVED"
              and e["payload"].get("prepared_event_id") == previous_id][-1]
    rebind["old_authority_inherited"] = True
    payload = {"prepared_event_id":prepared_id,"rebind":rebind,"correction_request":deepcopy(request),
               "derived_authority":{"policy":POLICY,"source_prepared_event_id":previous_id,
                                    "source_approval_event_id":source["event_id"]}}
    # CAS commits the grant and its immutable semantic-review receipt together.
    return store.append_batch(program_id,[{"event_type":"BUILD_AUTHORIZATION_APPROVED","payload":payload}],
                              expected_revision=expected_revision,idempotency_key=idempotency_key,created_at=created_at)[0]


def resolve_technical_attempt(store, program_id, prepared_id, attempt_id, *, evidence,
                              expected_revision, idempotency_key, created_at):
    request = {"prepared_event_id":prepared_id,"attempt_id":attempt_id,"evidence":evidence,
               "expected_revision":expected_revision}
    replay = store.idempotent_events(program_id,idempotency_key)
    if replay is not None:
        if len(replay) != 1 or replay[0]["payload"].get("technical_request") != request:
            raise IdempotencyConflictError("technical disposition key reused with different content")
        return replay[0]
    from .build_runtime import BuildController
    controller = BuildController(store,program_id,clock=lambda:_utc(created_at))
    events, prepared, plan = controller._current(prepared_id)
    if len(events) != expected_revision:
        raise RevisionConflictError("re-read blocked attempt before technical disposition")
    require(isinstance(evidence,dict) and set(evidence) == {"review","command_ids","effects","classification","public_basis"},
            "technical disposition requires bound commands, effects and host review")
    _host_review(evidence["review"],policy=TECHNICAL_POLICY)
    attempts, _ = project_execution_state(events,prepared_id)
    attempt = attempts.get(attempt_id)
    require(attempt is not None and attempt["status"] == "BLOCKED", "only a settled technical block is eligible")
    require(not any(a["status"] in {"IN_FLIGHT","UNKNOWN_SIDE_EFFECT"}
                    for a in project_budget_attempts(events,prepared_id).values()), "unknown effects require ordinary recovery")
    require([a for a in attempts.values() if a["workpack_id"] == attempt["workpack_id"]][-1]["attempt_id"] == attempt_id,
            "a later attempt supersedes this technical block")
    commands = _completed_commands(events,attempt)
    require(attempt.get("effects", {}).get("status") not in {"VIOLATION", "MISSING_REQUIRED"},
            "unresolved declared effects cannot be treated as a technical false block")
    ids = [c["command_id"] for c in commands]
    require(evidence["command_ids"] == ids,"technical disposition refers to different commands")
    _effects_review(evidence["effects"],ids)
    require(evidence["classification"] == "TECHNICAL_FALSE_BLOCK_PUBLIC_SCOPE_COMPLETE"
            and evidence["public_basis"] == prepared["acceptance_contracts"],
            "a genuine missing user decision cannot be relabeled as a technical block")
    require(commands[-1]["phase"] in {"IMPLEMENTATION", "PREFLIGHT"}
            and not any(c["phase"] == "VERIFICATION" for c in commands),
            "a completed producer/checker uses explicit checker correction, not production replay")
    require(all(c["result"].get("failure_domain") != "BUSINESS_ASSERTION" for c in commands),
            "product failures are not technical dispositions")
    # A model's CONTRACT_GAP report may itself be the technical false block.
    # The trusted host must explicitly review the unchanged public basis above;
    # the observer label alone neither grants retry nor proves a real user gap.
    # Structured user-stop/decision markers cannot be contradicted by a host label.
    require(not any(c["result"].get(k) for c in commands for k in
                    ("user_stop","human_decision_required","cancellation_reason")), "a user stop or real decision cannot be overridden")
    binding = {k:attempt[k] for k in ("prepared_event_id","attempt_id","proposal_event_id","workpack_id","job_id")}
    return store.append_batch(program_id,[{"event_type":"BUILD_ATTEMPT_RESOLVED","payload":{
        **binding,"status":"RETRY_ALLOWED","original_status":attempt.get("original_status",attempt["status"]),
        "reason":evidence["review"]["reason"],"technical_request":deepcopy(request),
        "host_disposition":deepcopy(evidence),"budget_reset":False,"old_output_accepted":False}}],
        expected_revision=expected_revision,idempotency_key=idempotency_key,created_at=created_at)[0]
