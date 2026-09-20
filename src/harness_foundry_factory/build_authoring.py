"""Persist generic *proposals* in the existing revision-based control store.

This source-engineering boundary does not create or approve a runtime. Plan
events are immutable inputs for future authorization; an event ID is a reference,
not a permission. No snapshots, receipts or additional databases are maintained.
"""

from copy import deepcopy
from typing import Any, Mapping

from .build_plan import compile_build_plan, validate_compiled_build_plan
from .build_review import validate_build_review, validate_review_reuse, validate_review_sources, review_summary
from .models import RequestValidationError, RevisionConflictError, canonical_json
from .store import ControlEventStore


PROPOSAL_EVENT = "BUILD_PLAN_PROPOSED"


def _require_revision_store(store: ControlEventStore) -> None:
    if store.storage_format != "REVISION_V1":
        raise RequestValidationError("generic proposals require a revision-format ControlEventStore; historical streams are unchanged")


def record_build_plan_proposal(store: ControlEventStore, requirement_ir: Mapping[str, Any], plan: Mapping[str, Any],
                               *, expected_revision: int, idempotency_key: str, created_at: str,
                               document_review=None) -> dict[str, Any]:
    """Validate and atomically record an unapproved plan without running it.

    The caller must already be allowed to author this local database. This API
    is not an authorization interface. The public host CLI delegates proposal
    recording here without approving or running it.
    """
    _require_revision_store(store)
    validate_build_review(document_review)
    compiled = compile_build_plan(requirement_ir, plan)
    validate_review_sources(document_review, requirement_ir)
    validate_compiled_build_plan(requirement_ir, plan, compiled)
    if type(expected_revision) is not int or expected_revision < 0:
        raise RequestValidationError("expected_revision must be a nonnegative integer")
    events = store.list_events(requirement_ir["program_id"])
    if expected_revision > len(events):
        raise RevisionConflictError("proposal refers to a control revision that does not exist")
    # Validate against the caller's version. append_batch performs transactional
    # CAS (or exact idempotent replay), including when another writer intervenes.
    proposals = [event for event in events[:expected_revision] if event["event_type"] == PROPOSAL_EVENT]
    for event in events:
        if event["event_type"] == PROPOSAL_EVENT:
            validate_review_reuse(document_review, event["payload"].get("document_review"))
    if proposals:
        previous = proposals[-1]["payload"]
        old_ir, old_plan = previous["requirement_ir"], previous["plan"]
        if requirement_ir["revision"] == old_ir["revision"]:
            if canonical_json(requirement_ir) != canonical_json(old_ir):
                raise RevisionConflictError("requirement content changed without a new requirement revision")
        elif requirement_ir["revision"] != old_ir["revision"] + 1:
            raise RevisionConflictError("requirement revisions must advance one version at a time")
        if plan["plan_id"] != old_plan["plan_id"] or plan["revision"] != old_plan["revision"] + 1:
            raise RevisionConflictError("revise the existing plan using its next revision")
    elif requirement_ir["revision"] != 1 or plan["revision"] != 1:
        raise RevisionConflictError("a new proposal stream starts at requirement and plan revision 1")
    return store.append_batch(requirement_ir["program_id"], [{"event_type": PROPOSAL_EVENT,
                              "payload": {"requirement_ir": dict(requirement_ir), "plan": dict(plan),
                                          "document_review": deepcopy(document_review)}}],
                              expected_revision=expected_revision, idempotency_key=idempotency_key,
                              created_at=created_at, exclusive_program=True)[0]


def _proposal_event(store: ControlEventStore, program_id: str, event_id: str | None) -> dict[str, Any]:
    _require_revision_store(store)
    events = [event for event in store.list_events(program_id) if event["event_type"] == PROPOSAL_EVENT
              and (event_id is None or event["event_id"] == event_id)]
    if not events:
        raise RequestValidationError("build proposal does not exist for this Program and event")
    return events[-1]


def _binding(event: Mapping[str, Any]) -> dict[str, Any]:
    plan = event["payload"]["plan"]
    return {"program_id": event["program_id"], "proposal_event_id": event["event_id"],
            "stream_revision": event["stream_revision"], "requirement_revision": plan["requirement_revision"],
            "plan_id": plan["plan_id"], "plan_revision": plan["revision"]}


def read_build_plan_proposal(store: ControlEventStore, program_id: str, *, event_id: str | None = None) -> dict[str, Any]:
    """Rebuild the declared plan from one immutable event, never from a JSON view."""
    event = _proposal_event(store, program_id, event_id)
    payload = event["payload"]
    compiled = compile_build_plan(payload["requirement_ir"], payload["plan"])
    validate_compiled_build_plan(payload["requirement_ir"], payload["plan"], compiled)
    return {"proposal_binding": _binding(event), "compiled_plan": compiled,
            "document_review": review_summary(payload.get("document_review"))}


def read_build_task_context(store: ControlEventStore, program_id: str, workpack_id: str,
                            *, event_id: str) -> dict[str, Any]:
    """Resolve a task's scope from a pinned proposal, with no fixed business flow.

    The context is for authoring/inspection, not yet a runnable command. Case
    commands remain unexecuted and source reading claims remain declarations.
    """
    if not isinstance(event_id, str) or not event_id:
        raise RequestValidationError("task context requires a pinned proposal event ID")
    event = _proposal_event(store, program_id, event_id)
    ir, plan = event["payload"]["requirement_ir"], event["payload"]["plan"]
    compiled = compile_build_plan(ir, plan)
    validate_compiled_build_plan(ir, plan, compiled)
    task = next((item for item in plan["workpacks"] if item["workpack_id"] == workpack_id), None)
    if task is None:
        raise RequestValidationError("Workpack does not exist in the pinned proposal")
    atoms = [atom for atom in ir["atoms"] if atom["atom_id"] in task["atom_ids"]]
    source_ids = {atom["source_id"] for atom in atoms} | {item["id"] for item in task["inputs"] if item["kind"] == "SOURCE"}
    source_ids.update(row["source_id"] for row in event["payload"].get("document_review", {}).get("documents", []))
    cases = {case["case_id"]: (kind, case) for kind in ("acceptance_cases", "negative_cases") for case in ir.get(kind, [])}
    context = {
        "status": "TASK_CONTEXT_NOT_AUTHORIZED", "proposal_binding": _binding(event),
        "workpack": task, "requirements": atoms,
        # Preserve non-atom context rather than silently dropping a global
        # requirement or constraint an intake adapter may have supplied.
        "requirement_context": {key: value for key, value in ir.items()
                                if key not in {"atoms", "sources", "acceptance_cases", "negative_cases"}},
        "sources": [source for source in ir["sources"] if source["source_id"] in source_ids],
        "artifact_inputs": {item["id"]: compiled["artifact_index"][item["id"]]
                            for item in task["inputs"] if item["kind"] == "ARTIFACT"},
        "cases": [{"kind": cases[check["case_id"]][0], "declaration": cases[check["case_id"]][1],
                   "verification": check} for check in task["verification"]],
        "authority_validated": False, "behavior_verified": False, "execution_started": False,
    }
    return deepcopy(context)
