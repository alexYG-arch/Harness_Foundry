"""Independent executable checks for the pure Lab protocol API.

Expected outcomes below do not import the producer or the implementation. A
runtime must invoke this suite inside its authorized isolated worker, not import
untrusted project code into the controller. This module dispatches no worker.
"""

from copy import deepcopy
import hashlib
import json


PROTOCOL_CASE_IDS = (
    "schema-valid", "schema-type", "schema-bound", "schema-missing", "schema-extra",
    "schema-external-ref", "schema-wrong-dialect", "public-job-unlisted-url",
    "public-job-duration_target_seconds", "public-job-output_video_count",
    "public-job-target_skill_execution_enabled", "public-job-skill_entrypoint_ref",
    "registry-load", "registry-resolve", "registry-unknown", "registry-malformed",
    "operator-known", "operator-unknown", "evidence-exact-bytes", "evidence-unknown",
    "evidence-not-bytes", "url-normalization", "url-not-repository", "job-immutable-identity",
    "job-revision-not-identity", "job-resolution-fields-required", "schema-content-binding",
    "schema-renderer-is-not-content",
)


def verify_protocol_primitives(api, job_request_schema):
    """Call actual API behavior; neither stdout PASS nor self-tests are inputs.

    These are protocol foundation checks. Full dynamic artifact-graph production,
    evaluator algorithms, leases, command receipts and Workpack acceptance are
    distinct requirements, not certified by this result.
    """
    rows = []

    def check(case_id, function, arguments, expected=None, error=None):
        args = deepcopy(arguments)
        before = deepcopy(args)
        try:
            actual = getattr(api, function)(*args)
            matched = error is None and type(actual) is type(expected) and actual == expected and args == before
            row = {"case_id": case_id, "status": "PASS" if matched else "FAIL"}
            if not matched:
                row["reason"] = "unexpected return value or input mutation"
        except Exception as exc:
            code = getattr(exc, "code", None)
            matched = error is not None and code == error and args == before
            row = {"case_id": case_id, "status": "PASS" if matched else
                   "INCONCLUSIVE" if code == "SCHEMA_DEPENDENCY_UNAVAILABLE" else "FAIL"}
            if not matched:
                row["reason"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)

    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
              "$defs": {"positive": {"type": "integer", "minimum": 1}},
              "properties": {"count": {"$ref": "#/$defs/positive"}},
              "required": ["count"], "unevaluatedProperties": False}
    for suffix, value, expected in (("valid", {"count": 2}, True), ("type", {"count": True}, False),
                                    ("bound", {"count": 0}, False), ("missing", {}, False),
                                    ("extra", {"count": 2, "other": 1}, False)):
        check("schema-" + suffix, "validate_instance", [schema, value], expected)
    check("schema-external-ref", "validate_instance", [{"$ref": "https://example.invalid/schema"}, {}],
          error="SCHEMA_CONTRACT_UNRESOLVED")
    check("schema-wrong-dialect", "validate_instance", [{"$schema": "http://json-schema.org/draft-07/schema#"}, {}],
          error="SCHEMA_DIALECT_UNSUPPORTED")
    request = {"request_id": "TEST-ONLY-PROTOCOL", "skill_url": "https://github.com/example/Unlisted-Protocol-Fixture",
               "requested_revision": "main", "skill_entrypoint_ref": "skills/demo/SKILL.md", "language": "zh-CN",
               "duration_target_seconds": 180, "output_video_count": 1, "target_skill_execution_enabled": False}
    check("public-job-unlisted-url", "validate_instance", [job_request_schema, request], True)
    for key, value in (("duration_target_seconds", 20), ("output_video_count", 2),
                       ("target_skill_execution_enabled", True), ("skill_entrypoint_ref", "../SKILL.md")):
        check("public-job-" + key, "validate_instance", [job_request_schema, {**request, key: value}], False)
    registry = {"evaluators": {"TEST-EVALUATOR": {"implementation_entrypoint": "test_only.evaluator:check"}}}
    check("registry-load", "load_evaluator_registry", [registry], registry["evaluators"])
    check("registry-resolve", "resolve_evaluator", [registry, "TEST-EVALUATOR"], registry["evaluators"]["TEST-EVALUATOR"])
    check("registry-unknown", "resolve_evaluator", [registry, "UNREGISTERED"], error="UNKNOWN_EVALUATOR")
    check("registry-malformed", "load_evaluator_registry", [{"evaluators": {"X": {}}}], error="EVALUATOR_REGISTRY_INVALID")
    check("operator-known", "require_operator", ["EQUALS", ["EQUALS", "SET_EQUALS"]], "EQUALS")
    check("operator-unknown", "require_operator", ["UNREGISTERED", ["EQUALS"]], error="UNKNOWN_OPERATOR")
    check("evidence-exact-bytes", "resolve_evidence_bytes", ["test://evidence", {"test://evidence": b"\x00exact\xff"}], b"\x00exact\xff")
    check("evidence-unknown", "resolve_evidence_bytes", ["test://missing", {"test://evidence": b"value"}], error="EVIDENCE_REF_UNAVAILABLE")
    check("evidence-not-bytes", "resolve_evidence_bytes", ["test://evidence", {"test://evidence": "PASS"}], error="EVIDENCE_REF_UNAVAILABLE")
    check("url-normalization", "normalize_skill_url", ["https://GITHUB.COM/Example/CaseSensitive.git/"],
          "https://github.com/Example/CaseSensitive")
    check("url-not-repository", "normalize_skill_url", ["https://github.com/Example/Repo/blob/main/SKILL.md"], error="SKILL_URL_INVALID")
    # Synthetic test-input hashes, not claims of real Git or network resolution.
    identity = {"request_id": "TEST-协议", "normalized_skill_url": "https://github.com/Example/Repo",
                "skill_entrypoint_ref": "SKILL.md", "resolved_commit_sha": hashlib.sha1(b"TEST-COMMIT").hexdigest(),
                "resolved_git_tree_oid": hashlib.sha1(b"TEST-TREE").hexdigest(),
                "resolved_tree_sha256": hashlib.sha256(b"TEST-TREE-BYTES").hexdigest(),
                "resolved_skill_entrypoint_sha256": hashlib.sha256(b"TEST-SKILL-BYTES").hexdigest()}
    expected_id = "JOB-" + hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                                     separators=(",", ":")).encode()).hexdigest()[:16].upper()
    check("job-immutable-identity", "derive_job_id", [identity], expected_id)
    check("job-revision-not-identity", "derive_job_id", [{**identity, "requested_revision": "another-branch"}], expected_id)
    incomplete = dict(identity)
    incomplete.pop("resolved_tree_sha256")
    check("job-resolution-fields-required", "derive_job_id", [incomplete], error="RESOLVED_JOB_IDENTITY_INVALID")
    template = {"type": "object", "required": ["repository_url"], "properties": {
        "repository_url": {"type": "string"}, "commit_sha": {"type": "string"},
        "unrelated": {"type": "integer", "minimum": 3}}, "x-invariants": ["KEEP_THIS_INVARIANT"]}
    job = {"job_id": expected_id, "source_id": "TEST-SOURCE", "repository_url": identity["normalized_skill_url"],
           "commit_sha": identity["resolved_commit_sha"], "tree_sha256": identity["resolved_tree_sha256"]}
    expected = deepcopy(template)
    expected["required"] += ["job_id", "source_id"]
    expected["properties"].update({key: {"const": job[key]} for key in ("job_id", "source_id", "repository_url", "commit_sha")})
    check("schema-content-binding", "specialize_artifact_schema", [template, job, "SOURCE_FREEZE_RECEIPT", []], expected)
    renderer = {"source_id": "TEST-RENDERER", "repository_url": "https://github.com/Example/Renderer",
                "commit_sha": hashlib.sha1(b"TEST-RENDERER").hexdigest(),
                "tree_sha256": hashlib.sha256(b"TEST-RENDERER-TREE").hexdigest(), "license_spdx": "MIT"}
    render_template = {"type": "object", "properties": {"repository_url": {"const": renderer["repository_url"]}}}
    render_values = {"job_id": job["job_id"], "source_id": job["source_id"],
                     "renderer_source_id": renderer["source_id"], "renderer_repository_url": renderer["repository_url"],
                     "renderer_commit_sha": renderer["commit_sha"], "renderer_tree_sha256": renderer["tree_sha256"],
                     "renderer_license_spdx": "MIT", "repository_url": renderer["repository_url"],
                     "commit_sha": renderer["commit_sha"], "tree_sha256": renderer["tree_sha256"], "license_spdx": "MIT",
                     "content_repository_url": job["repository_url"], "content_commit_sha": job["commit_sha"],
                     "content_tree_sha256": job["tree_sha256"]}
    expected_render = {"type": "object", "properties": {key: {"const": value} for key, value in render_values.items()},
                       "required": list(render_values)}
    check("schema-renderer-is-not-content", "specialize_artifact_schema", [render_template, job, "LOCAL_RENDER_RECEIPT", [renderer]], expected_render)
    statuses = {row["status"] for row in rows}
    return {"status": "FAIL" if "FAIL" in statuses else "INCONCLUSIVE" if "INCONCLUSIVE" in statuses else "PASS",
            "evidence_scope": "LAB_PROTOCOL_PRIMITIVES_ONLY", "cases": rows,
            "workpack_accepted": False, "execution_authorized": False}
