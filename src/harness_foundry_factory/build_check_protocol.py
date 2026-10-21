"""Public per-Case interface facts; no private oracle, credentials or authority."""

from copy import deepcopy


CHECKER_GUIDANCE = (
    "Use existing tool interfaces, cwd and interpreter/venv. Reuse an existing work-directory argument "
    "or the declared resource environment; add a path or bound-tool parameter only when actually missing, "
    "and propagate that value to the child that needs it. A dedicated approved scratch subtree inside "
    "the project is valid during development, as is an approved directory outside the project during "
    "read-only observation; exclude only that subtree from source protection. "
    "The public acceptance_contracts and per-Case verification_interfaces describe required outputs, "
    "not permission to read a private verifier. The host executes independent checks; implementers use "
    "only the public development tools assigned by their contract. verifier:// is a host command reference. "
    "When this task delivers a checker or adapter, follow its actual declared interface. Resource "
    "STRUCTURED_V1 writes the bound report in FOUNDRY_REPORT_DIR/summary.json with actual environment "
    "Case/command identities and every required check. An existing non-resource structured stdout "
    "interface uses CHECKS_PASS/exit 0 or CHECKS_FAILED/exit 1 with failure_kind ASSERTION, "
    "INFRASTRUCTURE or CONTRACT_GAP; reason is explanation. Other existing exit-code checks keep their "
    "original interface, without a new JSON requirement. Preserve underlying error evidence: only an "
    "actual public-contract assertion is ASSERTION; unexpected test/setup/discovery/process errors, "
    "zero tests, skipped required tests and expected failures leave required execution incomplete. "
    "Expected exceptions asserted by a passing test are normal. Reuse the existing test_execution "
    "adapter only when explicitly available; its workdir and interpreter parameters are optional adapter "
    "interfaces, not a new requirement for every tool. Prepare goals for the current case only unless "
    "the approved scope explicitly requires multiple cases; examples are not cumulative requirements. "
)


def verification_interfaces(task, scope):
    """Describe only referenced public protocols, never copy a resource profile."""
    result = []
    profiles = scope.get("verification_resources", {}).get("profiles", {})
    for check in task["verification"]:
        row = {"case_id": check["case_id"]}
        ref = check.get("resource_profile_ref")
        if ref is None:
            row.update(result_protocol="EXISTING_NON_RESOURCE_INTERFACE",
                       interface="Preserve the existing exit-code or structured stdout contract.")
        else:
            profile = profiles[ref]
            row.update(resource_profile_ref=ref,
                       result_protocol=profile["result_protocol"],
                       required_checks=deepcopy(profile["required_checks"]),
                       report_files=deepcopy(profile["report_files"]),
                       summary_environment="FOUNDRY_REPORT_DIR/summary.json",
                       scratch_environment="FOUNDRY_SCRATCH_DIR",
                       identity_environment={"case_id": "FOUNDRY_CASE_ID", "command_id": "FOUNDRY_COMMAND_ID"},
                       required_report_fields=["schema_version", "case_id", "command_id", "status", "checks", "errors"],
                       success={"status": "CHECKS_PASS", "exit_code": 0, "all_required_checks": "PASS", "errors": []},
                       failure="CHECKS_FAILED/exit 1; preserve actual ASSERTION, INFRASTRUCTURE or CONTRACT_GAP.")
            mode = profile["network"]["mode"]
            if mode == "LOCAL_SERVICE":
                row["additional_report_fields"] = {"services_stopped": "true after owned services stop"}
            elif mode == "REMOTE_SERVICE":
                row["additional_report_fields"] = {"external_effects": "NONE or CONFIRMED from actual accounting"}
        result.append(row)
    return result
