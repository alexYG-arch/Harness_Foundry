"""Explicit same-Program rebinding: shared usage, qualified acceptance, fresh authority.

This is not a cross-database migration or a new dispatcher. Historic events and
observations keep their original identities. Ordinary preparations are unchanged.
"""

from copy import deepcopy
from pathlib import Path

from .build_artifacts import file_identity, relative_path, superseded_artifacts
from .build_state import project_execution_state, project_budget_attempts, prepared_lineage, affected_workpacks
from .build_types import RequestValidationError, canonical_json


def _require(condition, message):
    if not condition:
        raise RequestValidationError(message)


def _event(events, identity, kind):
    found = next((e for e in events if e["event_id"] == identity and e["event_type"] == kind), None)
    _require(found is not None, "rebind reference is not in this Program's event stream")
    return found


def superseding_prepared(events, prepared_id):
    return next((e["payload"]["prepared_event_id"] for e in events
                 if e["event_type"] == "BUILD_AUTHORIZATION_APPROVED"
                 and prepared_id in e["payload"].get("rebind", {}).get("superseded_prepared_ids", [])), None)


def validate_rebind(events, previous_id, proposal, scope):
    """Validate the selected relationship, not a grant or acceptance import."""
    _require(isinstance(previous_id, str) and bool(previous_id.strip()), "rebind_from must identify an old preparation")
    old = _event(events, previous_id, "BUILD_AUTHORIZATION_PREPARED")["payload"]
    _require(superseding_prepared(events, previous_id) is None, "rebind must continue the latest linked preparation")
    _require(any(e["event_type"] == "BUILD_AUTHORIZATION_APPROVED" and e["payload"]["prepared_event_id"] == previous_id
                 for e in events), "rebind origin must have an actual prior approval")
    if old.get("rebind_from"):
        _require(any(e["event_type"] == "BUILD_AUTHORIZATION_APPROVED"
                     and e["payload"]["prepared_event_id"] == previous_id and "rebind" in e["payload"] for e in events),
                 "rebind origin has no committed continuation")
    _require(Path(old["scope"]["workspace_root"]).resolve() == Path(scope["workspace_root"]).resolve(),
             "rebind keeps the same implementation workspace")
    for key in ("max_attempts", "max_task_attempts"):
        _require(scope[key] == old["scope"][key], "rebind preserves original budget ceilings; do not subtract old usage twice")
    old_proposal = _event(events, old["proposal_event_id"], "BUILD_PLAN_PROPOSED")["payload"]
    before = {t["workpack_id"]: t for t in old_proposal["plan"]["workpacks"]}
    after = {t["workpack_id"]: t for t in proposal["plan"]["workpacks"]}
    _require(before.keys() == after.keys(), "explicit rebind keeps task identities; split/merge remains in its existing route")
    for key in before:
        for field in ("job_id", "artifacts", "depends_on"):
            _require(before[key][field] == after[key][field], "rebind cannot reassign task outputs, Jobs or budget ownership")
    return old


def _production_signature(events, proposal, prepared, task):
    public = deepcopy(task)
    public.pop("verification")
    atoms = [a for a in proposal["requirement_ir"]["atoms"] if a["atom_id"] in task["atom_ids"]]
    source_ids = {a["source_id"] for a in atoms} | {i["id"] for i in task["inputs"] if i["kind"] == "SOURCE"}
    snapshot = _event(events, prepared["source_event_id"], "BUILD_SOURCES_CAPTURED")["payload"]["snapshot"]
    sources = [s for s in snapshot["sources"] if s["source_id"] in source_ids]
    contracts = sorted({canonical_json(prepared["acceptance_contracts"][c["case_id"]]) for c in task["verification"]})
    return public, atoms, sources, contracts


def _check_signature(prepared, task):
    scope = prepared["scope"]
    profiles = scope.get("verification_resources", {}).get("profiles", {})
    refs = {c.get("resource_profile_ref") for c in task["verification"]} - {None}
    # Snapshot root UUIDs and resource allocation roots are not test semantics.
    # Named file identities and the actual check/tool configuration are.
    names = {arg.removeprefix("verifier://") for c in task["verification"] for arg in c["argv"] if arg.startswith("verifier://")}
    if refs:
        names.update(scope["verification_resources"].get("checker_files", []))
    tools = {c["argv"][0] for c in task["verification"]}
    tools.update(arg.removeprefix("executable://") for c in task["verification"] for arg in c["argv"] if arg.startswith("executable://"))
    return (task["verification"], {n: prepared["verifier_files"][n] for n in names}, {n: scope["executables"][n] for n in tools},
            scope["source_read_roots"], {r: profiles[r] for r in refs})


def approval_rebind(events, previous_id, new_prepared, new_proposal, *, extra_candidates=None):
    """Freeze a current qualification at the approval CAS; no command executes."""
    old = validate_rebind(events, previous_id, new_proposal, new_prepared["scope"])
    lineage = prepared_lineage(events, previous_id)
    for identity in lineage:
        attempts, _ = project_execution_state(events, identity)
        _require(not any(a["status"] in {"IN_FLIGHT", "UNKNOWN_SIDE_EFFECT"} for a in attempts.values()),
                 "rebind cannot bypass unresolved effects; reconcile the original command first")
    _, accepted = project_execution_state(events, previous_id)
    candidates = {**(extra_candidates or {}), **reverification_candidates(events, previous_id), **accepted}
    old_proposal = _event(events, old["proposal_event_id"], "BUILD_PLAN_PROPOSED")["payload"]
    after = {t["workpack_id"]: t for t in new_proposal["plan"]["workpacks"]}
    reuse, reverify, rebuild = {}, {}, set()
    history = project_budget_attempts(events, previous_id)
    superseded = superseded_artifacts(old_proposal["plan"], history)
    workspace = Path(new_prepared["scope"]["workspace_root"])
    for key, record in candidates.items():
        # A task may have been harmlessly replanned before its acceptance. Use
        # its actual accepted proposal, not the first plan's implementation.
        used = _event(events, record["proposal_event_id"], "BUILD_PLAN_PROPOSED")["payload"]
        task = next(t for t in used["plan"]["workpacks"] if t["workpack_id"] == key)
        old_binding = _event(events, record["prepared_event_id"], "BUILD_AUTHORIZATION_PREPARED")["payload"]
        if _production_signature(events, used, old_binding, task) != _production_signature(events, new_proposal, new_prepared, after[key]):
            rebuild.add(key)
            continue
        intact = all(identity in superseded or (
            relative_path(workspace, item["path"]).is_file() and
            file_identity(relative_path(workspace, item["path"])) == {k: item[k] for k in ("size", "sha256")})
            for identity, item in record["artifacts"].items())
        if not intact:
            rebuild.add(key)
        elif (not record.get("unaccepted_completed_implementation")
              and _check_signature(old_binding, task) == _check_signature(new_prepared, after[key])):
            reuse[key] = deepcopy(record)
        else:
            _require(not set(record["artifacts"]).intersection(superseded),
                     "changed checks require a consumed physical version; an explicit rebuild plan is needed")
            reverify[key] = deepcopy(record)
    # A changed producer removes downstream acceptance; never import a result
    # whose formal input is no longer accepted. Verification-only producers may
    # preserve their bytes, but consumers are rechecked after that decision.
    affected = affected_workpacks(new_proposal["plan"], rebuild | reverify.keys())
    for key in affected:
        if key in reuse:
            reverify[key] = reuse.pop(key)
    for key in affected_workpacks(new_proposal["plan"], rebuild):
        reuse.pop(key, None)
        reverify.pop(key, None)
    # Qualification carries artifact provenance, not the prior round's billing
    # policy. Only derive_checker_authorization may mark a NEW correction round
    # free; an ordinary later human rebind retains the historical charge rule.
    for record in reverify.values():
        for field in ("reverify_kind", "production_budget_charge", "checker_binding"):
            record.pop(field, None)
    return {"from_prepared_event_id": previous_id, "superseded_prepared_ids": lineage,
            "accepted": reuse, "verification_pending": reverify, "rebuild_workpack_ids": sorted(rebuild),
            "budget_reset": False, "old_authority_inherited": False}


def reverification_candidates(events, prepared_id):
    approved = next((e["payload"].get("rebind", {}) for e in reversed(events)
                     if e["event_type"] == "BUILD_AUTHORIZATION_APPROVED"
                     and e["payload"]["prepared_event_id"] == prepared_id), {})
    pending = deepcopy(approved.get("verification_pending", {}))
    attempts, _ = project_execution_state(events, prepared_id)
    for row in attempts.values():
        if row["status"] in {"ACCEPTED", "REJECTED", "INVALIDATED"}:
            pending.pop(row["workpack_id"], None)
    return pending
