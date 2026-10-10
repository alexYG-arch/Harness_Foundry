"""Descriptive Run Test reporting, never an oracle, controller or approval.

The trusted test host supplies chronological external evaluations and existing
evidence references. This module cannot authenticate them or prove semantic
coverage. Keep raw observations, failures and native/injected origins outside
target write roots. No state, commands, automatic retries or hashes are added.
"""
from copy import deepcopy
from pathlib import Path


COMPARISON_FIELDS = ("contract", "inputs", "executor", "tools", "permissions", "checker", "budget")


def factorial_summary(runs=()):
    """Describe a 2x2 Foundry/document comparison; never invent missing costs.

    One row is one independent task/run. The host supplies real evidence and
    condition identities. This function checks comparability, not authenticity
    or statistical significance. Empty cells remain NOT_RUN.
    """
    import math
    runs = deepcopy(list(runs))
    metrics = ("attempts", "human_interventions", "elapsed_seconds", "tokens", "cost")
    cells = {}
    seen = set()
    for row in runs:
        key = (row.get("foundry"), row.get("document"))
        if key[0] not in {"baseline", "upgraded"} or key[1] not in {"original", "clarified"}:
            raise ValueError("unknown comparison factor")
        if not row.get("run_id") or row["run_id"] in seen or not row.get("task_id") or not row.get("evidence_refs"):
            raise ValueError("distinct runs require task identity and independent evidence references")
        seen.add(row["run_id"])
        if row.get("outcome") not in {"PASS", "FAIL", "BLOCKED"}:
            raise ValueError("record an observed outcome; absent runs are not zero-cost failures")
        for metric in metrics:
            value = row.get(metric)
            if value is not None and (type(value) not in {int, float} or not math.isfinite(value) or value < 0):
                raise ValueError("metrics must be nonnegative finite numbers or null")
    for foundry in ("baseline", "upgraded"):
        for document in ("original", "clarified"):
            selected = [row for row in runs if (row["foundry"], row["document"]) == (foundry, document)]
            cells[foundry + "/" + document] = {
                "status": "OBSERVED" if selected else "NOT_RUN", "runs": selected,
                "completion_rate": sum(row["outcome"] == "PASS" for row in selected) / len(selected) if selected else None,
                "mean": {metric: sum(row[metric] for row in selected) / len(selected)
                         if selected and all(row.get(metric) is not None for row in selected) else None for metric in metrics}}
    differences = []
    if runs:
        # Different tasks have different inputs/contracts. Hold conditions fixed
        # across treatments of each task, not across unrelated tasks.
        for task_id in {row["task_id"] for row in runs}:
            comparable = [row for row in runs if row["task_id"] == task_id]
            for field in COMPARISON_FIELDS:
                first = comparable[0].get("conditions", {}).get(field)
                if not first or any(row.get("conditions", {}).get(field) != first for row in comparable):
                    differences.append(task_id + ":" + field)
        for row in runs:
            executor = row.get("conditions", {}).get("executor", {})
            if not isinstance(executor, dict) or not all(executor.get(key) for key in
                    ("requested_model", "effective_model", "client_version")):
                differences.append("effective_executor")
        cohorts = [sorted(row["task_id"] for row in cell["runs"]) for cell in cells.values()]
        if any(cohort != cohorts[0] for cohort in cohorts):
            differences.append("task_cohort")
    complete = all(cell["status"] == "OBSERVED" for cell in cells.values())
    return {"status": "NOT_RUN" if not runs else "INCOMPLETE" if not complete else
            "NOT_COMPARABLE" if differences else "MATCHED_OBSERVABLE_CONDITIONS",
            "cells": cells, "differing_or_missing": sorted(set(differences)),
            "improvement_demonstrated": False, "evidence_authenticity_verified": False,
            "limitations": ["Descriptive only; independent obligation/effect checks and real held-out uses remain required."]
                + (["SERVICE_REVISION_UNKNOWN"] if any(not isinstance(row.get("conditions", {}).get("executor"), dict)
                    or not row["conditions"]["executor"].get("service_revision") for row in runs) else [])}


def capture_harness(root, files):
    """Capture only the predeclared fixed Harness files, not business/runtime data.

    Call immediately before and after each use. Small file bytes are encoded for
    JSON, not hashed; the host retains these observations with the original run.
    The declared inventory must cover the fixed rules/scripts/configuration.
    This helper cannot decide whether the host's inventory is semantically full.
    """
    root = Path(root).resolve(strict=True)
    if not files or len(set(files)) != len(files):
        raise ValueError("declare a nonempty unique Harness file inventory")
    result = {}
    for name in files:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Harness inventory paths must be relative and contained")
        source = (root / path).resolve(strict=True)
        if not source.is_relative_to(root):
            raise ValueError("Harness inventory resolves outside its root")
        result[name] = source.read_bytes().hex()
    return result


def reuse_summary(uses, *, package_ref, harness_ref):
    """Describe the two selected uses of the final version; retain all history.

    These are host-observed independent sessions and external business results,
    not a model's HARNESS_USE.md. No inference from two argv/data variations.
    """
    uses = deepcopy(list(uses))
    reasons = []
    if len(uses) != 2:
        reasons.append("TWO_DISTINCT_USES_REQUIRED")
    else:
        first, second = uses
        for field in ("task_id", "task_kind", "session_ref"):
            if not first.get(field) or not second.get(field) or first[field] == second[field]:
                reasons.append("DISTINCT_" + field.upper() + "_REQUIRED")
        snapshot = first.get("harness_before")
        if not isinstance(snapshot, dict) or not snapshot:
            reasons.append("HARNESS_BYTES_MISSING")
        for use in uses:
            if (not package_ref or not harness_ref or use.get("package_ref") != package_ref
                    or use.get("harness_ref") != harness_ref):
                reasons.append("VERSION_DIFFERS_FROM_FINAL")
            if use.get("result") != "PASS" or not use.get("evidence_refs"):
                reasons.append("EXTERNAL_USE_RESULT_MISSING_OR_FAILED")
            if not use.get("harness_before") or use.get("harness_before") != snapshot or use.get("harness_after") != snapshot:
                reasons.append("HARNESS_BYTES_CHANGED_OR_MISSING")
    return {"status": "NOT_DEMONSTRATED" if reasons else "OBSERVED",
            "reasons": sorted(set(reasons)), "uses": uses,
            "evidence_authenticity_verified": False}


def comparison_summary(before=None, after=None):
    """Compare recorded conditions, not performance or statistical significance."""
    result = {"status": "NOT_REQUESTED", "improvement_demonstrated": False,
              "limitations": [], "differing_or_missing": []}
    if before is None and after is None:
        return result
    left, right = (row or {} for row in (before, after))
    a, b = left.get("conditions", {}), right.get("conditions", {})
    for field in COMPARISON_FIELDS:
        if not a.get(field) or not b.get(field) or a[field] != b[field]:
            result["differing_or_missing"].append(field)
    for conditions in (a, b):
        executor = conditions.get("executor", {})
        if not isinstance(executor, dict) or not all(executor.get(key) for key in
                ("requested_model", "effective_model", "client_version")):
            result["differing_or_missing"].append("effective_executor")
        if not isinstance(executor, dict) or not executor.get("service_revision"):
            result["limitations"].append("SERVICE_REVISION_UNKNOWN")
    if not left.get("evidence_refs") or not right.get("evidence_refs"):
        result["differing_or_missing"].append("evidence_refs")
    result["differing_or_missing"] = sorted(set(result["differing_or_missing"]))
    result["limitations"] = sorted(set(result["limitations"]))
    result["status"] = "NOT_COMPARABLE" if result["differing_or_missing"] else "MATCHED_OBSERVABLE_CONDITIONS"
    return result


def summarize(evaluations, required_scenarios, *, reuse_uses=(), comparison=None):
    """One case, chronological evaluation rounds: never replace first with best.

    Each round carries evaluation_ref/package_ref/harness_ref, results keyed by
    scenario and evidence_refs. Keep costs, mechanism observations, origins and
    unrun reasons as supplied. Missing usage stays missing, not zero. A new
    final Harness/package needs its own coverage; no union of historical PASSes.
    """
    history = deepcopy(list(evaluations))
    if not history or not required_scenarios:
        raise ValueError("report requires evaluations and the declared scenario set")
    seen = set()
    for row in history:
        ref = row.get("evaluation_ref")
        if not ref or ref in seen or not row.get("package_ref") or "harness_ref" not in row:
            raise ValueError("evaluations need distinct references and explicit versions")
        seen.add(ref)
        if not isinstance(row.get("results"), dict):
            raise ValueError("evaluation results must be a scenario mapping")
    def view(row):
        result = deepcopy(row)
        result["results"] = {key: row["results"].get(key, "NOT_RUN") for key in required_scenarios}
        result["missing_scenarios"] = [key for key in required_scenarios if key not in row["results"]]
        return result
    final = history[-1]
    return {"status": "DESCRIPTIVE_REPORT_NOT_ACCEPTANCE", "initial": view(history[0]),
            "final": view(final), "history": history,
            "reuse": reuse_summary(reuse_uses, package_ref=final["package_ref"], harness_ref=final["harness_ref"]),
            "comparison": comparison_summary(**comparison) if comparison is not None else comparison_summary(),
            "release_accepted": False, "harness_e2e_verified": False}
