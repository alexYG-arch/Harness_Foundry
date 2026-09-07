"""Pure protocol primitives shared with a future built external Lab.

No process, network, filesystem, lease or authority access. Supplied identities
and captured evidence are inputs, not proof that source resolution/leases ran.
Full artifact-graph recompilation and evaluator execution belong to the Lab CLI.
"""

from copy import deepcopy
import hashlib
import json
import re
from collections.abc import Mapping
from urllib.parse import urlsplit


class ProtocolError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def validate_instance(schema, instance):
    """False means an invalid instance, never an unavailable schema/validator."""
    if not isinstance(schema, (Mapping, bool)):
        raise ProtocolError("SCHEMA_CONTRACT_INVALID", "schema must be an object or boolean")
    if isinstance(schema, Mapping) and schema.get("$schema") not in {
            None, "https://json-schema.org/draft/2020-12/schema"}:
        raise ProtocolError("SCHEMA_DIALECT_UNSUPPORTED", "only JSON Schema 2020-12 is supported")
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry
        from referencing.exceptions import NoSuchResource
    except ImportError as exc:
        raise ProtocolError("SCHEMA_DEPENDENCY_UNAVAILABLE", str(exc)) from exc

    def no_external_resource(uri):
        raise NoSuchResource(ref=uri)

    try:
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema, registry=Registry(retrieve=no_external_resource)).is_valid(instance)
    except Exception as exc:
        raise ProtocolError("SCHEMA_CONTRACT_UNRESOLVED", str(exc)) from exc


def load_evaluator_registry(registry):
    """Load declarations, not Python entrypoints or executable evaluator code."""
    evaluators = registry.get("evaluators") if isinstance(registry, Mapping) else None
    if not isinstance(evaluators, Mapping) or not evaluators:
        raise ProtocolError("EVALUATOR_REGISTRY_INVALID", "non-empty evaluator map required")
    for name, declaration in evaluators.items():
        if (not isinstance(name, str) or not name or not isinstance(declaration, Mapping)
                or not isinstance(declaration.get("implementation_entrypoint"), str)
                or not declaration["implementation_entrypoint"]):
            raise ProtocolError("EVALUATOR_REGISTRY_INVALID", "invalid evaluator declaration")
    return deepcopy(dict(evaluators))


def resolve_evaluator(registry, evaluator_id):
    evaluators = load_evaluator_registry(registry)
    if not isinstance(evaluator_id, str) or evaluator_id not in evaluators:
        raise ProtocolError("UNKNOWN_EVALUATOR", "evaluator is not in the supplied frozen registry")
    return evaluators[evaluator_id]


def require_operator(operator, registered_operators):
    if (not isinstance(registered_operators, (list, tuple))
            or not all(isinstance(name, str) and name for name in registered_operators)
            or len(set(registered_operators)) != len(registered_operators)):
        raise ProtocolError("OPERATOR_REGISTRY_INVALID", "unique registered operator names required")
    if not isinstance(operator, str) or operator not in registered_operators:
        raise ProtocolError("UNKNOWN_OPERATOR", "operator is not registered")
    return operator


def resolve_evidence_bytes(reference, captured_evidence):
    """Exact in-memory lookup only; the caller owns resolution and read leases."""
    if (not isinstance(reference, str) or not isinstance(captured_evidence, Mapping)
            or reference not in captured_evidence or not isinstance(captured_evidence[reference], bytes)):
        raise ProtocolError("EVIDENCE_REF_UNAVAILABLE", "exact captured bytes are required")
    return captured_evidence[reference]


def normalize_skill_url(value):
    if not isinstance(value, str):
        raise ProtocolError("SKILL_URL_INVALID", "public GitHub repository URL required")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.netloc.lower() != "github.com"
            or parsed.query or parsed.fragment
            or not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?", parsed.path)):
        raise ProtocolError("SKILL_URL_INVALID", "public GitHub repository URL required")
    path = parsed.path.rstrip("/").removesuffix(".git")
    if not path.rsplit("/", 1)[-1]:
        raise ProtocolError("SKILL_URL_INVALID", "repository name is empty")
    return "https://github.com" + path


def derive_job_id(resolved_identity):
    """Compute the declared ID; this does not attest that resolution occurred."""
    fields = ("request_id", "normalized_skill_url", "skill_entrypoint_ref", "resolved_commit_sha",
              "resolved_git_tree_oid", "resolved_tree_sha256", "resolved_skill_entrypoint_sha256")
    if not isinstance(resolved_identity, Mapping) or any(
            not isinstance(resolved_identity.get(key), str) or not resolved_identity[key] for key in fields):
        raise ProtocolError("RESOLVED_JOB_IDENTITY_INVALID", "all immutable identity fields are required")
    material = {key: resolved_identity[key] for key in fields}
    if material["normalized_skill_url"] != normalize_skill_url(material["normalized_skill_url"]):
        raise ProtocolError("RESOLVED_JOB_IDENTITY_INVALID", "identity URL is not normalized")
    if not re.fullmatch(r"(?!/)(?!.*(?:^|/)\.\.(?:/|$))(?:[^/]+/)*SKILL\.md", material["skill_entrypoint_ref"]):
        raise ProtocolError("RESOLVED_JOB_IDENTITY_INVALID", "invalid Skill entrypoint")
    for key, size in (("resolved_commit_sha", 40), ("resolved_git_tree_oid", 40),
                      ("resolved_tree_sha256", 64), ("resolved_skill_entrypoint_sha256", 64)):
        if not re.fullmatch(rf"[0-9a-f]{{{size}}}", material[key]):
            raise ProtocolError("RESOLVED_JOB_IDENTITY_INVALID", "immutable identity digest is malformed")
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "JOB-" + hashlib.sha256(encoded).hexdigest()[:16].upper()


def specialize_artifact_schema(schema, job, artifact_kind, repository_jobs):
    """Deep-copy a schema and bind source/renderer fields; not a graph compiler.

    This is the existing producer binding algorithm, extracted for use by the
    built Lab without importing the Factory compiler or mutable authoring state.
    """
    bound = deepcopy(dict(schema))
    properties = bound.setdefault("properties", {})

    def require_fields(fields):
        required = bound.setdefault("required", [])
        if not isinstance(required, list):
            required = bound["required"] = []
        for field in fields:
            if field not in required:
                required.append(field)

    require_fields(["job_id", "source_id"])
    properties["job_id"] = {"const": job["job_id"]}
    properties["source_id"] = {"const": job["source_id"]}
    if artifact_kind == "LOCAL_RENDER_RECEIPT":
        declared_repository = properties.get("repository_url")
        renderer_url = declared_repository.get("const") if isinstance(declared_repository, Mapping) else None
        renderer = next((item for item in repository_jobs if item.get("repository_url") == renderer_url), None)
        if renderer is not None:
            fields = {"renderer_source_id": renderer.get("source_id"),
                      "renderer_repository_url": renderer.get("repository_url"),
                      "renderer_commit_sha": renderer.get("commit_sha"),
                      "renderer_tree_sha256": renderer.get("tree_sha256"),
                      "renderer_license_spdx": renderer.get("license_spdx"),
                      "repository_url": renderer.get("repository_url"), "commit_sha": renderer.get("commit_sha"),
                      "tree_sha256": renderer.get("tree_sha256"), "license_spdx": renderer.get("license_spdx")}
            require_fields(fields)
            for field, value in fields.items():
                if value:
                    properties[field] = {"const": value}
        fields = {"content_repository_url": job.get("repository_url"),
                  "content_commit_sha": job.get("commit_sha"), "content_tree_sha256": job.get("tree_sha256")}
        require_fields(fields)
        for field, value in fields.items():
            if value:
                properties[field] = {"const": value}
    else:
        for field in ("repository_url", "commit_sha", "git_tree_oid", "tree_sha256"):
            if field in properties and job.get(field):
                properties[field] = {"const": job[field]}
    if "exact_commit_sha" in properties and job.get("commit_sha"):
        properties["exact_commit_sha"] = {"const": job["commit_sha"]}
    if artifact_kind == "TARGET_SKILL_EXECUTION_GATE_RECEIPT":
        properties["target_skill_id"] = {"const": job["source_id"]}
    return bound
