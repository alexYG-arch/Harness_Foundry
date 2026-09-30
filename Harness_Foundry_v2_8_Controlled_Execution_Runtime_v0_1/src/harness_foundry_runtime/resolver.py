"""Resolve one provider profile into Hash-bound per-Workpack overlays."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from .engine import (
    RuntimeViolation,
    _node_workpacks,
    _validate_resolved_manifest,
    register_command_overlays,
)
from .store import RuntimeStore
from .util import (
    file_sha256,
    json_sha256,
    lexical_path,
    lexically_within,
    read_json,
    utc_now,
    write_json,
)


def resolve_command_overlays(
    execution_root: str | Path,
    resolver_bundle_path: str | Path,
) -> dict[str, Any]:
    store = RuntimeStore(execution_root)
    state = store.load_state()
    bundle = read_json(Path(resolver_bundle_path).expanduser().resolve())
    if bundle.get("schema_version") != "1.0":
        return _failure(
            "RESOLVER_SCHEMA_UNSUPPORTED",
            str(bundle.get("schema_version")),
        )
    if bundle.get("resolver_kind") != "WORKPACK_AUTOMATION_RESOLVER_BUNDLE":
        return _failure(
            "RESOLVER_KIND_INVALID",
            str(bundle.get("resolver_kind")),
        )
    for field in ("program_id", "epoch_id", "candidate_content_sha256"):
        if bundle.get(field) != state.get(field):
            return _failure("RESOLVER_BINDING_MISMATCH", field)
    if state.get("driver", {}).get("runtime_verified") is not True:
        return _failure(
            "DRIVER_RUNTIME_NOT_VERIFIED",
            "bootstrap verification is required",
        )
    authorization = state.get("authorization")
    if (
        isinstance(authorization, Mapping)
        and authorization.get("status") == "ACTIVE"
    ):
        return _failure(
            "RESOLUTION_WITH_AUTHORIZATION_FORBIDDEN",
            str(authorization.get("authorization_id")),
        )
    profiles = bundle.get("profiles")
    default_profile_id = bundle.get("default_profile_id")
    node_ids = bundle.get("node_ids")
    if (
        not isinstance(profiles, Mapping)
        or not profiles
        or default_profile_id not in profiles
        or not isinstance(node_ids, list)
        or not node_ids
        or len(node_ids) != len(set(node_ids))
    ):
        return _failure("RESOLVER_PROFILE_BINDINGS_INVALID", "profiles/node_ids")
    node_profiles = bundle.get("node_profile_bindings", {})
    workpack_profiles = bundle.get("workpack_profile_bindings", {})
    if not isinstance(node_profiles, Mapping) or not isinstance(
        workpack_profiles, Mapping
    ):
        return _failure("RESOLVER_PROFILE_BINDINGS_INVALID", "bindings")
    if (
        not set(node_profiles).issubset(set(node_ids))
        or any(
            profile_id not in profiles
            for profile_id in node_profiles.values()
        )
        or any(
            profile_id not in profiles
            for profile_id in workpack_profiles.values()
        )
    ):
        return _failure(
            "RESOLVER_PROFILE_BINDINGS_INVALID",
            "unknown node/profile binding",
        )

    candidate = Path(state["candidate_root"])
    nodes = {
        node["node_id"]: node
        for node in state.get("control_plan", {}).get("nodes", [])
    }
    manifests: dict[str, dict[str, Any]] = {}
    cwd_paths: set[Path] = set()
    selected_workpacks: set[str] = set()
    for node_id in node_ids:
        node = nodes.get(node_id)
        if (
            node is None
            or node.get("auto_advance_eligible") is not True
            or node.get("human_gate") is True
            or node_id in state.get("completed_nodes", [])
        ):
            return _failure("RESOLVER_NODE_NOT_AUTOMATABLE", str(node_id))
        workpacks = _node_workpacks(node) or [f"PIPELINE:{node_id}"]
        selected_workpacks.update(workpacks)
        steps = []
        for workpack_id in workpacks:
            profile_id = (
                workpack_profiles.get(workpack_id)
                or node_profiles.get(node_id)
                or default_profile_id
            )
            profile = profiles.get(profile_id)
            if not isinstance(profile, Mapping) or not isinstance(
                profile.get("commands"), list
            ):
                return _failure(
                    "RESOLVER_PROFILE_MISSING",
                    f"{node_id}:{workpack_id}:{profile_id}",
                )
            context = {
                "{{HF_CANDIDATE_ROOT}}": str(candidate),
                "{{HF_EXECUTION_ROOT}}": str(state["execution_root"]),
                "{{HF_NODE_ID}}": str(node_id),
                "{{HF_WORKPACK_ID}}": str(workpack_id),
                "{{HF_WORKPACK_REF}}": _workpack_ref(
                    candidate, node, workpack_id
                ),
            }
            commands = _substitute(deepcopy(profile["commands"]), context)
            for command in commands:
                if not isinstance(command, dict):
                    return _failure(
                        "RESOLVER_COMMAND_INVALID",
                        f"{node_id}:{workpack_id}",
                    )
                command["workpack_id"] = workpack_id
                executable = Path(str(command.get("executable_abs", "")))
                argv = command.get("argv")
                cwd = lexical_path(str(command.get("cwd_abs", "")))
                command["cwd_abs"] = str(cwd)
                if (
                    not executable.is_absolute()
                    or not executable.is_file()
                    or not isinstance(argv, list)
                    or not argv
                ):
                    return _failure(
                        "RESOLVER_COMMAND_RUNTIME_INVALID",
                        str(command.get("command_id")),
                    )
                executable_hash = file_sha256(executable)
                configured_hash = command.get("executable_sha256")
                if configured_hash not in {None, "AUTO", executable_hash}:
                    return _failure(
                        "RESOLVER_EXECUTABLE_HASH_MISMATCH",
                        str(command.get("command_id")),
                    )
                command["executable_sha256"] = executable_hash
                if not cwd.exists():
                    if not _cwd_may_be_created(state, node, cwd):
                        return _failure(
                            "RESOLVER_CWD_CREATION_FORBIDDEN", str(cwd)
                        )
                    cwd_paths.add(cwd)
            steps.append(
                {
                    "workpack_id": workpack_id,
                    "profile_id": profile_id,
                    "commands": commands,
                }
            )
        manifests[node_id] = {
            "schema_version": "1.0",
            "node_id": node_id,
            "environment_id": node.get("environment_id"),
            "workpack_steps": steps,
        }

    if not set(workpack_profiles).issubset(selected_workpacks):
        return _failure(
            "RESOLVER_PROFILE_BINDINGS_INVALID",
            "unknown workpack binding",
        )
    for cwd in sorted(cwd_paths, key=str):
        cwd.mkdir(parents=True, exist_ok=True)
    try:
        for node_id, manifest in manifests.items():
            _validate_resolved_manifest(
                state,
                nodes[node_id],
                manifest,
                authorized_write_roots=None,
            )
    except RuntimeViolation as exc:
        return _failure(
            exc.code,
            exc.message,
            writes_performed=bool(cwd_paths),
        )
    overlay = {
        "schema_version": "1.0",
        "overlay_kind": "RESOLVED_COMMAND_OVERLAY_BUNDLE",
        "program_id": state["program_id"],
        "epoch_id": state["epoch_id"],
        "candidate_content_sha256": state["candidate_content_sha256"],
        "manifests": manifests,
    }
    resolver_hash = json_sha256(bundle)
    overlay_hash = json_sha256(overlay)
    resolver_root = lexical_path(state["execution_root"]) / (
        "control_plane/resolver_inputs"
    )
    resolver_path = resolver_root / f"{resolver_hash}.json"
    overlay_path = resolver_root / f"{resolver_hash}-{overlay_hash}.overlay.json"
    write_json(resolver_path, bundle)
    write_json(overlay_path, overlay)
    result = register_command_overlays(execution_root, overlay_path)
    if result.get("status") != "PASS":
        return {**result, "writes_performed": True}

    resolver_sha256 = file_sha256(resolver_path)
    overlay_sha256 = file_sha256(overlay_path)
    state_root = lexical_path(state["execution_root"])

    def recorded(current: dict[str, Any]) -> None:
        for path, digest in (
            (resolver_path, resolver_sha256),
            (overlay_path, overlay_sha256),
        ):
            relative = path.relative_to(state_root).as_posix()
            current["evidence_index"][relative] = digest
        current.setdefault("resolver_history", []).append(
            {
                "resolver_bundle_sha256": resolver_sha256,
                "generated_overlay_sha256": overlay_sha256,
                "node_ids": list(node_ids),
                "resolved_at": utc_now(),
                "execution_authority_granted": False,
            }
        )

    store.append(
        "COMMAND_OVERLAYS_RESOLVED",
        {
            "resolver_bundle_sha256": resolver_sha256,
            "generated_overlay_sha256": overlay_sha256,
            "node_ids": list(node_ids),
            "execution_authority_granted": False,
        },
        mutate=recorded,
    )
    return {
        **result,
        "resolver_bundle_sha256": resolver_sha256,
        "generated_overlay_sha256": overlay_sha256,
        "resolved_node_ids": list(node_ids),
        "cwd_directories_created": len(cwd_paths),
    }


def _workpack_ref(
    candidate: Path,
    node: Mapping[str, Any],
    workpack_id: str,
) -> str:
    candidate = lexical_path(candidate)
    references = []
    declared = node.get("project_workpack_index_ref")
    if isinstance(declared, str):
        references.append(candidate / declared)
    references.append(candidate / "WORKPACK_INDEX.json")
    for index_path in references:
        index_path = lexical_path(index_path)
        if not lexically_within(index_path, candidate):
            continue
        if not index_path.is_file():
            continue
        document = read_json(index_path)
        for row in document.get("workpacks", []):
            if row.get("workpack_id") != workpack_id:
                continue
            ref = row.get("workpack_ref")
            if isinstance(ref, str):
                resolved_ref = lexical_path(index_path.parent / ref)
                if lexically_within(resolved_ref, candidate):
                    return str(resolved_ref)
    return str(candidate)


def _cwd_may_be_created(
    state: Mapping[str, Any],
    node: Mapping[str, Any],
    cwd: Path,
) -> bool:
    if not lexically_within(cwd, state["execution_root"]):
        return False
    roots = [
        lexical_path(path)
        for path in node.get("allowed_write_paths", [])
    ]
    return any(
        lexically_within(cwd, root) or lexically_within(root, cwd)
        for root in roots
    )


def _substitute(value: Any, context: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        for token, replacement in context.items():
            value = value.replace(token, replacement)
        return value
    if isinstance(value, list):
        return [_substitute(item, context) for item in value]
    if isinstance(value, dict):
        return {
            key: _substitute(item, context)
            for key, item in value.items()
        }
    return value


def _failure(
    code: str,
    message: str,
    *,
    writes_performed: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "status": "FAIL",
        "blocking_findings": [{"code": code, "message": message}],
        "writes_performed": writes_performed,
        "commands_executed": False,
        "execution_authority_granted": False,
    }
