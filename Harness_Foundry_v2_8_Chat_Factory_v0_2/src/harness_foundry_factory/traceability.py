"""Deterministic Requirement IR Atom-to-engineering coverage routing."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


WORKPACK_PROJECTS = {
    "LAB-PROTOCOL": "EXTERNAL_CONFORMANCE_LAB",
    "LAB-CLI": "EXTERNAL_CONFORMANCE_LAB",
    "LAB-FIXTURES": "EXTERNAL_CONFORMANCE_LAB",
    "LAB-SELFTEST": "EXTERNAL_CONFORMANCE_LAB",
    "LAB-CERTIFICATION": "EXTERNAL_CONFORMANCE_LAB",
    "LINK-PROTOCOL": "CONFORMANCE_LINKAGE_REVIEW",
    "LINK-CLI": "CONFORMANCE_LINKAGE_REVIEW",
    "LINK-SELFTEST": "CONFORMANCE_LINKAGE_REVIEW",
    "LINK-PREFLIGHT": "CONFORMANCE_LINKAGE_REVIEW",
    "LINK-D": "CONFORMANCE_LINKAGE_REVIEW",
    "MB-G0": "MAIN_HARNESS_BUILD",
    "MB-P1": "MAIN_HARNESS_BUILD",
    "MB-P2": "MAIN_HARNESS_BUILD",
    "MB-P3": "MAIN_HARNESS_BUILD",
    "MB-P4": "MAIN_HARNESS_BUILD",
    "MB-RELEASE-CANDIDATE": "MAIN_HARNESS_BUILD",
}

WORKPACK_STAGE_COMPATIBILITY = {
    "MB-G0": ("G0", "C0"),
    "MB-P1": ("P1", "C1"),
    "MB-P2": ("P2", "C2"),
    "MB-P3": ("P3", "C3"),
    "MB-P4": ("P4_BUILD_INPUT", "RELEASE_PIPELINE"),
    "MB-RELEASE-CANDIDATE": (
        "RELEASE_PIPELINE",
        "C4",
        "CERTIFIED_RELEASE",
    ),
}

PHASE_MARKERS = (
    ("G0", "G0", "MB-G0"),
    ("C0", "C0", "MB-G0"),
    ("P1", "P1", "MB-P1"),
    ("C1", "C1", "MB-P1"),
    ("P2", "P2", "MB-P2"),
    ("C2", "C2", "MB-P2"),
    ("P3", "P3", "MB-P3"),
    ("C3", "C3", "MB-P3"),
    ("P4", "P4_BUILD_INPUT", "MB-P4"),
    ("C4", "C4", "MB-RELEASE-CANDIDATE"),
)


def normalize_ir_coverage(requirement_ir: Mapping[str, Any]) -> dict[str, Any]:
    """Return an IR with exactly one explicit, deterministic edge per Atom."""

    ir = deepcopy(dict(requirement_ir))
    explicit = {
        str(item.get("atom_id")): deepcopy(dict(item))
        for item in ir.get("coverage_edges", [])
        if isinstance(item, Mapping) and item.get("atom_id")
    }
    normalized: list[dict[str, Any]] = []
    for atom in ir.get("atoms", []):
        if not isinstance(atom, Mapping) or not atom.get("atom_id"):
            continue
        atom_id = str(atom["atom_id"])
        edge = explicit.get(atom_id)
        if edge is None or str(edge.get("routing_basis", "")).startswith(
            "DERIVED_"
        ):
            edge = _derive_edge(atom)
        normalized.append(_normalize_edge(atom, edge))
    ir["coverage_edges"] = normalized
    return ir


def _normalize_edge(
    atom: Mapping[str, Any], edge: Mapping[str, Any]
) -> dict[str, Any]:
    atom_id = str(atom["atom_id"])
    workpack_ids = _unique_strings(edge.get("workpack_ids", []))
    stage_ids = _unique_strings(edge.get("stage_ids", []))
    release_step_ids = _unique_strings(edge.get("release_step_ids", []))
    if not workpack_ids or not stage_ids:
        derived = _derive_edge(atom)
        workpack_ids = workpack_ids or list(derived["workpack_ids"])
        stage_ids = stage_ids or list(derived["stage_ids"])
        release_step_ids = release_step_ids or list(derived["release_step_ids"])
    owner_project_ids = _unique_strings(
        edge.get(
            "owner_project_ids",
            [WORKPACK_PROJECTS[value] for value in workpack_ids if value in WORKPACK_PROJECTS],
        )
    )
    return {
        "atom_id": atom_id,
        "workpack_ids": workpack_ids,
        "stage_ids": stage_ids,
        "release_step_ids": release_step_ids,
        "owner_project_ids": owner_project_ids,
        "routing_basis": str(
            edge.get("routing_basis") or "EXPLICIT_USER_OR_CHAT_CONFIRMED"
        ),
        "status": "PLANNED_NOT_VERIFIED",
    }


def _derive_edge(atom: Mapping[str, Any]) -> dict[str, Any]:
    semantic_text = " ".join(
        str(value)
        for value in (
            atom.get("text_or_lossless_paraphrase", ""),
            atom.get("owner", ""),
            atom.get("verification_mode", ""),
            *atom.get("order_constraints", []),
            *atom.get("error_semantics", []),
            *atom.get("compatibility_constraints", []),
        )
    ).upper()
    owner = str(atom.get("owner", "")).upper()
    workpack_ids: list[str] = []
    stage_ids: list[str] = []
    release_step_ids: list[str] = []

    for marker, stage_id, workpack_id in PHASE_MARKERS:
        if marker in semantic_text:
            stage_ids.append(stage_id)
            workpack_ids.append(workpack_id)

    if "LINKAGE" in owner or "READ_ONLY_LINKAGE" in semantic_text:
        if any(term in semantic_text for term in ("INSTALLED", "HANDSHAKE", " D ")):
            workpack_ids.append("LINK-D")
            release_step_ids.append("LINKAGE_D_INSTALLED_HANDSHAKE")
            stage_ids.append("RELEASE_PIPELINE")
        else:
            workpack_ids.append("LINK-PREFLIGHT")
            release_step_ids.append("LINKAGE_A_INTERFACE_COMPLETENESS")
            stage_ids.append("RELEASE_PIPELINE")
    if "LAB" in owner or "CONFORMANCE_LAB" in semantic_text:
        if any(term in semantic_text for term in ("CERT", "INSTALLED", "TAMPER")):
            workpack_ids.append("LAB-CERTIFICATION")
            release_step_ids.append(
                "LAB_INSTALLED_POSITIVE_NEGATIVE_TAMPER_TESTS"
            )
            stage_ids.extend(("RELEASE_PIPELINE", "C4"))
        else:
            workpack_ids.append("LAB-SELFTEST")
            stage_ids.append("G0")

    runtime_terms = (
        "RUNTIME",
        "ENTRYPOINT",
        "INSTALL",
        "ARTIFACT",
        "RELEASE",
        "DRIVER",
        "CODEX",
        "RECEIPT",
    )
    if not workpack_ids and any(term in semantic_text for term in runtime_terms):
        workpack_ids.extend(("MB-P4", "MB-RELEASE-CANDIDATE"))
        stage_ids.extend(("P4_BUILD_INPUT", "RELEASE_PIPELINE"))
        if any(term in semantic_text for term in ("INSTALL", "ENTRYPOINT", "ORIGIN")):
            release_step_ids.append("INSTALLED_TARGET_DESCRIPTOR")

    if not workpack_ids:
        workpack_ids.append("MB-G0")
    if not stage_ids:
        stage_ids.append("G0")
    return {
        "atom_id": str(atom["atom_id"]),
        "workpack_ids": _unique_strings(workpack_ids),
        "stage_ids": _unique_strings(stage_ids),
        "release_step_ids": _unique_strings(release_step_ids),
        "owner_project_ids": _unique_strings(
            [
                WORKPACK_PROJECTS[value]
                for value in workpack_ids
                if value in WORKPACK_PROJECTS
            ]
        ),
        "routing_basis": "DERIVED_FROM_ATOM_OWNER_PHASE_AND_SEMANTICS",
        "status": "PLANNED_NOT_VERIFIED",
    }


def _unique_strings(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    result: list[str] = []
    for value in values:
        text = str(value)
        if text and text not in result:
            result.append(text)
    return result
