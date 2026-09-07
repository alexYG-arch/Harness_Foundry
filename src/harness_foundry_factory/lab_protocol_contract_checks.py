"""Independent protocol checks over the complete frozen registry/schema catalog.

This does not execute evaluator algorithms, source resolution or the Job graph.
Those are later Lab responsibilities. Call project APIs only inside the approved
worker. The controller may derive expected case IDs without calling project code.
"""

from copy import deepcopy
import hashlib
from collections.abc import Mapping


def contract_case_ids(registry, catalog):
    return ["frozen-registry-load", *["frozen-registry-resolve:" + key for key in sorted(registry["evaluators"])],
            "frozen-schema-binding-set", *["frozen-schema-binding:" + key for key in sorted(catalog)
                if isinstance(catalog[key], Mapping) and isinstance(catalog[key].get("schema"), Mapping)]]


def _binding_matches(template, bound, job, kind, repositories):
    """Check required changes and lossless preservation, not a producer replay."""
    if not isinstance(bound, Mapping):
        return False
    required_values = {"job_id": job["job_id"], "source_id": job["source_id"]}
    props = template.get("properties", {})
    if kind == "LOCAL_RENDER_RECEIPT":
        url = props.get("repository_url", {}).get("const")
        renderer = next((item for item in repositories if item.get("repository_url") == url), None)
        if renderer is not None:
            for field in ("source_id", "repository_url", "commit_sha", "tree_sha256", "license_spdx"):
                required_values["renderer_" + field] = renderer.get(field)
            for field in ("repository_url", "commit_sha", "tree_sha256", "license_spdx"):
                required_values[field] = renderer.get(field)
        required_values.update({"content_" + field: job[field] for field in ("repository_url", "commit_sha", "tree_sha256")})
    else:
        required_values.update({field: job[field] for field in ("repository_url", "commit_sha", "git_tree_oid", "tree_sha256")
                                if field in props})
    added_required = list(required_values) if kind == "LOCAL_RENDER_RECEIPT" else ["job_id", "source_id"]
    if "exact_commit_sha" in props:
        required_values["exact_commit_sha"] = job["commit_sha"]
    if kind == "TARGET_SKILL_EXECUTION_GATE_RECEIPT":
        required_values["target_skill_id"] = job["source_id"]
    expected_required = list(template.get("required", []))
    for field in added_required:
        if field not in expected_required:
            expected_required.append(field)
    if bound.get("required") != expected_required:
        return False
    old, new = deepcopy(dict(template)), deepcopy(dict(bound))
    old.pop("required", None)
    new.pop("required", None)
    old_props, new_props = old.setdefault("properties", {}), new.setdefault("properties", {})
    for field, value in required_values.items():
        if not value:
            continue
        if new_props.get(field) != {"const": value}:
            return False
        old_props.pop(field, None)
        new_props.pop(field, None)
    return old == new


def verify_frozen_protocol_contract(api, interface, registry, catalog):
    """Exercise every frozen declaration, retaining failures rather than sampling."""
    rows = []

    def check(case_id, operation):
        try:
            matched = operation()
            rows.append({"case_id": case_id, "status": "PASS" if matched is True else "FAIL"})
        except Exception as exc:
            rows.append({"case_id": case_id,
                         "status": "INCONCLUSIVE" if isinstance(exc, ImportError) else "FAIL",
                         "diagnostic": f"{type(exc).__name__}: {exc}"})

    def registry_call(method, *args):
        value = deepcopy(registry)
        returned = getattr(api, method)(value, *args)
        expected = registry["evaluators"] if not args else registry["evaluators"][args[0]]
        return returned == expected and value == registry

    check("frozen-registry-load", lambda: registry_call("load_evaluator_registry"))
    for name in sorted(registry["evaluators"]):
        check("frozen-registry-resolve:" + name, lambda name=name: registry_call("resolve_evaluator", name))
    entries = [(key, catalog[key]) for key in sorted(catalog)
               if isinstance(catalog[key], Mapping) and isinstance(catalog[key].get("schema"), Mapping)]
    check("frozen-schema-binding-set", lambda: interface["dynamic_specialization_contract"]["schema_template_bindings"]
          == [{"atom_id": key, "artifact_kind": profile.get("artifact_kind", "")} for key, profile in entries])

    def specialize(profile):
        from jsonschema import Draft202012Validator
        repositories = interface["frozen_certification_fixtures"]
        # Explicit synthetic protocol inputs, not claims of Git resolution or Job execution.
        for suffix in ("A", "B"):
            job = {"job_id": "JOB-PROTOCOL-TEST-" + suffix, "source_id": "SRC-PROTOCOL-TEST-" + suffix,
                   "repository_url": "https://github.com/ProtocolFixture/Unlisted" + suffix,
                   "commit_sha": hashlib.sha1(("TEST-COMMIT-" + suffix).encode()).hexdigest(),
                   "git_tree_oid": hashlib.sha1(("TEST-GIT-TREE-" + suffix).encode()).hexdigest(),
                   "tree_sha256": hashlib.sha256(("TEST-TREE-BYTES-" + suffix).encode()).hexdigest()}
            template, given_job, given_repositories = deepcopy(profile["schema"]), deepcopy(job), deepcopy(repositories)
            bound = api.specialize_artifact_schema(template, given_job, profile["artifact_kind"], given_repositories)
            Draft202012Validator.check_schema(bound)
            if (template != profile["schema"] or given_job != job or given_repositories != repositories
                    or not _binding_matches(profile["schema"], bound, job, profile["artifact_kind"], repositories)):
                return False
        return True

    for key, profile in entries:
        check("frozen-schema-binding:" + key, lambda profile=profile: specialize(profile))
    statuses = {row["status"] for row in rows}
    return {"status": "FAIL" if "FAIL" in statuses else "INCONCLUSIVE" if "INCONCLUSIVE" in statuses else "PASS",
            "cases": rows, "evidence_scope": "FROZEN_PROTOCOL_DECLARATIONS_ONLY",
            "workpack_accepted": False, "source_resolution_executed": False, "job_graph_executed": False}
