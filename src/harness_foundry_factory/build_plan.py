"""Domain-neutral build-plan compilation; no authority, storage or execution.

The existing Start Package compiler remains a historical compatibility surface.
New plans declare their own Workpacks, Jobs, artifacts and acceptance cases:
they never pass through its fixed project routing or schema enrichment. Integer
revisions identify a proposed plan; only a future controller transaction can
bind it to approved requirements. A successful compile is not that transaction.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any, Mapping

from .models import RequestValidationError, SAFE_ID_RE, canonical_json


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise RequestValidationError(message, details={"reason_code": code})


def _fields(value: Any, fields: set[str], label: str) -> None:
    _require(isinstance(value, Mapping) and set(value) == fields,
             "BUILD_PLAN_FIELDS_INVALID", f"{label} requires exactly {sorted(fields)}")


def _id(value: Any, label: str) -> None:
    _require(isinstance(value, str) and SAFE_ID_RE.fullmatch(value) is not None,
             "BUILD_PLAN_ID_INVALID", f"{label} must be a nonempty path-safe identifier")


def _text(value: Any, label: str) -> None:
    _require(isinstance(value, str) and bool(value.strip()),
             "BUILD_PLAN_TEXT_MISSING", f"{label} must be nonempty text")


def _ids(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    _require(isinstance(value, list) and (bool(value) or not nonempty),
             "BUILD_PLAN_LIST_INVALID", f"{label} must be a list")
    for item in value:
        _id(item, label)
    _require(len(value) == len(set(value)), "BUILD_PLAN_DUPLICATE_ID", f"{label} contains duplicate IDs")
    return value


def _index(rows: Any, key: str, label: str, *, nonempty: bool = True) -> dict[str, Any]:
    _require(isinstance(rows, list) and (bool(rows) or not nonempty),
             "BUILD_PLAN_LIST_INVALID", f"{label} must be a list")
    result = {}
    for row in rows:
        _require(isinstance(row, Mapping), "BUILD_PLAN_FIELDS_INVALID", f"{label} entries must be objects")
        identifier = row.get(key)
        _id(identifier, f"{label}.{key}")
        _require(identifier not in result, "BUILD_PLAN_DUPLICATE_ID", f"duplicate {label} ID: {identifier}")
        result[identifier] = row
    return result


def _artifact_path(value: Any) -> PurePosixPath:
    _text(value, "artifact.path")
    path = PurePosixPath(value)
    _require(not path.is_absolute() and path.as_posix() == value and value != "."
             and ".." not in path.parts and "\\" not in value and ":" not in value
             and not any(ord(character) < 32 for character in value),
             "BUILD_PLAN_ARTIFACT_PATH_INVALID", "artifact paths must be canonical relative file paths")
    _require(path.parts[0] not in {".git", ".harness-foundry"},
             "BUILD_PLAN_ARTIFACT_PATH_INVALID", "artifacts cannot own controller or Git state")
    return path


def _requirement_catalog(requirement_ir: Mapping[str, Any]) -> tuple[dict, dict, dict]:
    _require(isinstance(requirement_ir, Mapping), "BUILD_PLAN_FIELDS_INVALID", "requirement_ir must be an object")
    _id(requirement_ir.get("program_id"), "requirement_ir.program_id")
    revision = requirement_ir.get("revision")
    _require(type(revision) is int and revision > 0, "BUILD_PLAN_REVISION_INVALID", "requirements need a positive revision")
    target = requirement_ir.get("target")
    _require(isinstance(target, Mapping), "BUILD_PLAN_FIELDS_INVALID", "requirement_ir.target must be an object")
    _id(target.get("id"), "target.id")
    _text(target.get("mission"), "target.mission")
    for field in ("scope", "non_goals"):
        values = target.get(field)
        _require(isinstance(values, list) and (bool(values) or field == "non_goals"),
                 "BUILD_PLAN_LIST_INVALID", f"target.{field} must be a list")
        for value in values:
            _text(value, f"target.{field}")
    # Declared unresolved questions are not resolved by filling structural fields.
    for field in ("open_questions", "source_conflicts"):
        rows = requirement_ir.get(field, [])
        _require(isinstance(rows, list), "BUILD_PLAN_LIST_INVALID", f"{field} must be a list")
        for row in rows:
            _require(isinstance(row, Mapping), "BUILD_PLAN_FIELDS_INVALID", f"{field} entries must be objects")
            _require(row.get("blocking") is False or row.get("status") == "RESOLVED",
                     "BUILD_PLAN_REQUIREMENT_UNRESOLVED", f"unresolved {field} cannot be compiled")
    atoms = _index(requirement_ir.get("atoms"), "atom_id", "atoms")
    for atom in atoms.values():
        _text(atom.get("text_or_lossless_paraphrase"), "atom.text_or_lossless_paraphrase")
    cases = _index(requirement_ir.get("acceptance_cases"), "case_id", "acceptance_cases")
    negatives = _index(requirement_ir.get("negative_cases", []), "case_id", "negative_cases", nonempty=False)
    _require(not set(cases).intersection(negatives), "BUILD_PLAN_DUPLICATE_ID", "case IDs must be unique across case kinds")
    cases.update(negatives)
    for case in cases.values():
        refs = _ids(case.get("atom_ids"), "case.atom_ids", nonempty=True)
        _require(set(refs) <= atoms.keys(), "BUILD_PLAN_REFERENCE_UNKNOWN", "case refers to an unknown requirement")
        _text(case.get("description"), "case.description")
    sources = _index(requirement_ir.get("sources", []), "source_id", "sources", nonempty=False)
    for source in sources.values():
        _require(source.get("loaded_completely") is True, "BUILD_PLAN_SOURCE_INCOMPLETE", "declared source has not been fully read")
        _text(source.get("path_or_uri"), "source.path_or_uri")
    for atom in atoms.values():
        _id(atom.get("source_id"), "atom.source_id")
        _require(atom.get("source_id") in sources, "BUILD_PLAN_REFERENCE_UNKNOWN", "requirement has no declared source")
        _text(atom.get("source_locator"), "atom.source_locator")
    return atoms, cases, sources


def validate_build_plan(requirement_ir: Mapping[str, Any], plan: Mapping[str, Any]) -> None:
    """Check declared scope, ownership, coverage and dependencies, not behavior.

    Commands are data only. We do not infer that an argv proves its Case, that
    a source was actually read, or that supplied revisions are authoritative.
    These require intake review, independent execution and controller binding.
    """
    atoms, cases, sources = _requirement_catalog(requirement_ir)
    _fields(plan, {"schema_version", "plan_id", "revision", "requirement_revision", "workpacks"}, "plan")
    _require(plan["schema_version"] == "1.0", "BUILD_PLAN_VERSION_UNSUPPORTED", "unsupported build-plan schema")
    _id(plan["plan_id"], "plan.plan_id")
    _require(type(plan["revision"]) is int and plan["revision"] > 0,
             "BUILD_PLAN_REVISION_INVALID", "plan revision must be a positive integer")
    _require(type(plan["requirement_revision"]) is int and plan["requirement_revision"] == requirement_ir["revision"],
             "BUILD_PLAN_REQUIREMENT_REVISION_MISMATCH", "plan targets a different requirement revision")
    workpacks = _index(plan["workpacks"], "workpack_id", "workpacks")
    artifacts: dict[str, dict] = {}
    paths: dict[PurePosixPath, list[str]] = {}
    covered_atoms: set[str] = set()
    covered_cases: set[str] = set()
    for workpack_id, workpack in workpacks.items():
        _fields(workpack, {"workpack_id", "job_id", "executor", "goal", "depends_on", "atom_ids",
                           "inputs", "artifacts", "verification"} | ({"local_argv"}
                           if "local_argv" in workpack else set()), f"workpack {workpack_id}")
        _id(workpack["job_id"], "workpack.job_id")
        _require(workpack["executor"] in ("CODEX", "LOCAL"), "BUILD_PLAN_EXECUTOR_UNSUPPORTED", "executor must be CODEX or LOCAL")
        if "local_argv" in workpack:
            _require(workpack["executor"] == "LOCAL" and isinstance(workpack["local_argv"], list)
                     and bool(workpack["local_argv"]), "BUILD_PLAN_LOCAL_COMMAND_INVALID",
                     "only LOCAL workpacks may declare a nonempty local_argv")
            for argument in workpack["local_argv"]:
                _require(isinstance(argument, str) and bool(argument.strip()) and "\x00" not in argument,
                         "BUILD_PLAN_LOCAL_COMMAND_INVALID", "argv requires nonempty text without NUL")
        _text(workpack["goal"], "workpack.goal")
        dependencies = _ids(workpack["depends_on"], "workpack.depends_on")
        _require(set(dependencies) <= workpacks.keys() and workpack_id not in dependencies,
                 "BUILD_PLAN_DEPENDENCY_INVALID", "unknown or self dependency")
        atom_ids = _ids(workpack["atom_ids"], "workpack.atom_ids", nonempty=True)
        _require(set(atom_ids) <= atoms.keys(), "BUILD_PLAN_REFERENCE_UNKNOWN", "workpack refers to an unknown requirement")
        covered_atoms.update(atom_ids)
        outputs = _index(workpack["artifacts"], "artifact_id", "workpack.artifacts")
        for artifact_id, artifact in outputs.items():
            _fields(artifact, {"artifact_id", "path"} | ({"replaces_artifact_id"}
                    if "replaces_artifact_id" in artifact else set()), "artifact")
            if "replaces_artifact_id" in artifact:
                _id(artifact["replaces_artifact_id"], "artifact.replaces_artifact_id")
            _require(artifact_id not in artifacts, "BUILD_PLAN_ARTIFACT_OWNER_CONFLICT", "artifact has multiple owners")
            path = _artifact_path(artifact["path"])
            _require(not any(path in old.parents or old in path.parents for old in paths),
                     "BUILD_PLAN_ARTIFACT_PATH_CONFLICT", "artifact file and directory paths overlap")
            paths.setdefault(path, []).append(artifact_id)
            artifacts[artifact_id] = {"workpack_id": workpack_id, "job_id": workpack["job_id"], "path": artifact["path"]}
            if "replaces_artifact_id" in artifact:
                artifacts[artifact_id]["replaces_artifact_id"] = artifact["replaces_artifact_id"]
        verification = workpack["verification"]
        _require(isinstance(verification, list) and bool(verification),
                 "BUILD_PLAN_VERIFICATION_MISSING", "every workpack needs independently runnable verification")
        local_cases: set[str] = set()
        for check in verification:
            _fields(check, {"case_id", "argv", "artifact_ids"}, "verification")
            case_id = check["case_id"]
            _id(case_id, "verification.case_id")
            _require(case_id in cases, "BUILD_PLAN_REFERENCE_UNKNOWN", "verification refers to an unknown case")
            _require(case_id not in local_cases, "BUILD_PLAN_DUPLICATE_ID", "duplicate workpack verification")
            local_cases.add(case_id)
            covered_cases.add(case_id)
            _require(set(cases[case_id]["atom_ids"]) <= set(atom_ids),
                     "BUILD_PLAN_CASE_OWNER_MISMATCH", "case requirements must be owned by its verifying workpack")
            verified_artifacts = _ids(check["artifact_ids"], "verification.artifact_ids", nonempty=True)
            _require(set(verified_artifacts) <= outputs.keys(),
                     "BUILD_PLAN_CASE_OWNER_MISMATCH", "verification must name this workpack's outputs")
            _require(isinstance(check["argv"], list) and bool(check["argv"]),
                     "BUILD_PLAN_VERIFICATION_MISSING", "verification argv must be a nonempty list")
            for argument in check["argv"]:
                _text(argument, "verification.argv")
        _require(set(atom_ids) <= {atom for case in local_cases for atom in cases[case]["atom_ids"]},
                 "BUILD_PLAN_REQUIREMENT_UNVERIFIED", "every owned requirement needs a declared check")
        _require(set(outputs) <= {artifact for check in verification for artifact in check["artifact_ids"]},
                 "BUILD_PLAN_ARTIFACT_UNVERIFIED", "every output needs a declared check")
    _require(covered_atoms == atoms.keys(), "BUILD_PLAN_REQUIREMENT_UNCOVERED", "plan omits requirements")
    _require(covered_cases == cases.keys(), "BUILD_PLAN_CASE_UNCOVERED", "plan omits acceptance or declared negative cases")

    # Topological closure supplies both cycle detection and transitive input
    # reachability. It does not impose a serial execution order on independent work.
    ancestors: dict[str, set[str]] = {}
    pending = set(workpacks)
    while pending:
        ready = sorted(key for key in pending if set(workpacks[key]["depends_on"]) <= ancestors.keys())
        _require(bool(ready), "BUILD_PLAN_DEPENDENCY_CYCLE", "workpack dependencies contain a cycle")
        for key in ready:
            parents = workpacks[key]["depends_on"]
            ancestors[key] = set(parents).union(*(ancestors[parent] for parent in parents))
            pending.remove(key)
    for workpack_id, workpack in workpacks.items():
        inputs = workpack["inputs"]
        _require(isinstance(inputs, list), "BUILD_PLAN_LIST_INVALID", "workpack.inputs must be a list")
        seen = set()
        for item in inputs:
            _fields(item, {"kind", "id"}, "input")
            _id(item["id"], "input.id")
            _require(item["kind"] in ("SOURCE", "ARTIFACT"), "BUILD_PLAN_INPUT_KIND_INVALID", "unsupported input kind")
            identity = (item["kind"], item["id"])
            _require(identity not in seen, "BUILD_PLAN_DUPLICATE_ID", "duplicate input")
            seen.add(identity)
            catalog = sources if item["kind"] == "SOURCE" else artifacts
            _require(item["id"] in catalog, "BUILD_PLAN_REFERENCE_UNKNOWN", "input does not resolve")
            if item["kind"] == "ARTIFACT":
                _require(artifacts[item["id"]]["workpack_id"] in ancestors[workpack_id],
                         "BUILD_PLAN_INPUT_DEPENDENCY_MISSING", "artifact producer must be a predecessor")
    _validate_artifact_revisions(workpacks, artifacts, paths, ancestors)


def _validate_artifact_revisions(workpacks: Mapping[str, Any], artifacts: Mapping[str, Any],
                                 paths: Mapping[PurePosixPath, list[str]], ancestors: Mapping[str, set[str]]) -> None:
    """A shared workspace has one current version per file, not immutable copies.

    Exact-path replacement is allowed, but old-version readers must finish before
    its replacement begins. This is a static scheduling constraint, not a claim
    that an artifact's current bytes have been verified or preserved.
    """
    replacements: dict[str, str] = {}
    for artifact_id, artifact in artifacts.items():
        previous_id = artifact.get("replaces_artifact_id")
        if previous_id is None:
            continue
        previous = artifacts.get(previous_id)
        _require(previous is not None and previous["path"] == artifact["path"],
                 "BUILD_PLAN_REPLACEMENT_INVALID", "replacement must name a declared version of the same file")
        owner = artifact["workpack_id"]
        _require(previous["workpack_id"] in ancestors[owner]
                 and {"kind": "ARTIFACT", "id": previous_id} in workpacks[owner]["inputs"],
                 "BUILD_PLAN_REPLACEMENT_INPUT_MISSING", "replacement must consume a predecessor's file version")
        _require(previous_id not in replacements, "BUILD_PLAN_ARTIFACT_PATH_CONFLICT",
                 "two outputs cannot replace the same file version")
        replacements[previous_id] = artifact_id
    for versions in paths.values():
        # Each file has one initial version and a single connected replacement
        # chain. Predecessor checks above already rule out replacement cycles.
        _require(sum("replaces_artifact_id" not in artifacts[key] for key in versions) == 1,
                 "BUILD_PLAN_ARTIFACT_PATH_CONFLICT", "shared file paths require an explicit replacement chain")
    for workpack_id, workpack in workpacks.items():
        for item in workpack["inputs"]:
            if item["kind"] != "ARTIFACT" or item["id"] not in replacements:
                continue
            replacement_owner = artifacts[replacements[item["id"]]]["workpack_id"]
            _require(workpack_id == replacement_owner or workpack_id in ancestors[replacement_owner],
                     "BUILD_PLAN_ARTIFACT_READ_ORDER_INVALID",
                     "an old file version must be consumed before its replacement; add an ordering dependency")


def compile_build_plan(requirement_ir: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]:
    """Compile only declarations, with no fixed stages, business schemas or hashes."""
    validate_build_plan(requirement_ir, plan)
    result = {
        "schema_version": "1.0", "status": "PLAN_COMPILED_NOT_AUTHORIZED",
        "requirement_binding": {"program_id": requirement_ir["program_id"], "revision": requirement_ir["revision"],
                                "target_id": requirement_ir["target"]["id"]},
        "plan": deepcopy(dict(plan)),
        "artifact_index": {}, "requirement_coverage": {},
        "authority_validated": False, "behavior_verified": False,
        "writes_performed": False, "execution_started": False,
    }
    for workpack in plan["workpacks"]:
        for artifact in workpack["artifacts"]:
            result["artifact_index"][artifact["artifact_id"]] = {
                "workpack_id": workpack["workpack_id"], "job_id": workpack["job_id"], "path": artifact["path"],
            }
            if "replaces_artifact_id" in artifact:
                result["artifact_index"][artifact["artifact_id"]]["replaces_artifact_id"] = artifact["replaces_artifact_id"]
        for atom_id in workpack["atom_ids"]:
            result["requirement_coverage"].setdefault(atom_id, []).append(workpack["workpack_id"])
    return result


def validate_compiled_build_plan(requirement_ir: Mapping[str, Any], plan: Mapping[str, Any],
                                 compiled: Mapping[str, Any]) -> None:
    """Independently check the producer projection against supplied declarations.

    Does not call the producer or repair its output. Neither this check nor its
    inputs can serve as runtime authorization or semantic acceptance evidence.
    """
    validate_build_plan(requirement_ir, plan)
    _fields(compiled, {"schema_version", "status", "requirement_binding", "plan", "artifact_index",
                       "requirement_coverage", "authority_validated", "behavior_verified",
                       "writes_performed", "execution_started"}, "compiled plan")
    _require(compiled["schema_version"] == "1.0" and compiled["status"] == "PLAN_COMPILED_NOT_AUTHORIZED"
             and all(compiled[key] is False for key in ("authority_validated", "behavior_verified", "writes_performed", "execution_started")),
             "BUILD_PLAN_FALSE_COMPLETION", "static compilation cannot claim authority, execution or acceptance")
    # JSON type identity matters: Python dict equality equates True with 1.
    # Compare canonical values directly, without adding a digest or receipt.
    _require(canonical_json(compiled["requirement_binding"]) == canonical_json({"program_id": requirement_ir["program_id"],
              "revision": requirement_ir["revision"], "target_id": requirement_ir["target"]["id"]})
             and canonical_json(compiled["plan"]) == canonical_json(plan),
             "BUILD_PLAN_PROJECTION_MISMATCH", "producer changed declared plan or requirement binding")
    artifacts = compiled["artifact_index"]
    coverage = compiled["requirement_coverage"]
    _require(isinstance(artifacts, Mapping) and isinstance(coverage, Mapping),
             "BUILD_PLAN_PROJECTION_MISMATCH", "compiled indices must be objects")
    declared_outputs = {item["artifact_id"] for row in plan["workpacks"] for item in row["artifacts"]}
    _require(set(artifacts) == declared_outputs and set(coverage) == {row["atom_id"] for row in requirement_ir["atoms"]},
             "BUILD_PLAN_PROJECTION_MISMATCH", "compiled indices omit or inject declarations")
    for workpack in plan["workpacks"]:
        for artifact in workpack["artifacts"]:
            expected = {"workpack_id": workpack["workpack_id"], "job_id": workpack["job_id"], "path": artifact["path"]}
            if "replaces_artifact_id" in artifact:
                expected["replaces_artifact_id"] = artifact["replaces_artifact_id"]
            _require(artifacts[artifact["artifact_id"]] == expected,
                     "BUILD_PLAN_PROJECTION_MISMATCH", "compiled artifact ownership differs")
    for atom_id, owners in coverage.items():
        _require(owners == [row["workpack_id"] for row in plan["workpacks"] if atom_id in row["atom_ids"]],
                 "BUILD_PLAN_PROJECTION_MISMATCH", "compiled requirement coverage differs")
