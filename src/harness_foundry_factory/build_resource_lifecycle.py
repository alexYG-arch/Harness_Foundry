"""Coordinate a command's declared resources without owning build state.

The controller still reserves attempts, persists command intent, checks current
permission before dispatch and commits acceptance. This module connects the
existing resource adapters to that lifecycle; it never grants authority, starts
a process, resolves credentials during preparation/recovery, or resets budgets.
"""

from .build_types import RequestValidationError
from .process_observation import CommandObservation
from .resource_credentials import resolve_credentials
from .resource_observation import CredentialObservation, finish_resource_observation
from .verification_resources import allocate_resources, materialize_product_copy, resolve_resource_argv


def prepare_resource_invocation(invocation, *, config, identity, workspace_root,
                                checked_artifacts, verifier_files, verifier_root):
    """Allocate once and return a binding for the controller's command intent.

    Allocation and the existing copy operation precede persistence as before.
    An interrupted allocation is not a recoverable command and is not silently
    adopted. A known copy-preparation failure retains the allocated tree and is
    persisted as an unstarted result by the controller, without dispatch.
    """
    resource = allocate_resources(config, invocation["resource_profile_ref"], identity)
    resource["checked_artifacts"] = checked_artifacts
    resource["verifier_files"] = verifier_files
    # The approved snapshot supplies checker/oracle inputs. Product-relative
    # reads keep their original cwd unless a product copy was explicitly chosen.
    resource["verifier_root"] = verifier_root
    resource["env"]["FOUNDRY_VERIFIER_ROOT"] = verifier_root
    preparation_failure = None
    try:
        materialize_product_copy(resource, workspace_root)
    except RequestValidationError:
        preparation_failure = {
            "status": "VALIDATION_FAILED", "workload_started": False,
            "automatic_retry_allowed": False,
            "failure_domain": "VERIFIER_INFRASTRUCTURE_OR_UNCLASSIFIED",
            "reason_code": "PRODUCT_COPY_PREPARATION_FAILED",
            "resource_result_reason": "declared product inputs could not be copied; verifier was not started",
            "receiver": "HOST_RESOURCE_PREPARATION"}
    prepared = {**invocation, "resource_binding": resource,
                "argv": resolve_resource_argv(invocation["argv"], resource),
                "write_roots": resource["write_roots"], "environment": resource["env"],
                "network": resource["network"]}
    if "product_copy" in resource:
        prepared = {**prepared, "cwd": resource["product_copy"]["root"],
                    "read_roots": [*invocation["read_roots"], resource["product_copy"]["root"]]}
    return prepared, preparation_failure


def resource_dispatch_hooks(invocation, observation):
    """Return a lazy native credential hook; never put secret values in binding.

    The existing receiver invokes the provider at its dispatch boundary. The
    provider's wrapper evaluates raw reports before redaction and records a
    safe durable capture, so recovery has no reason to resolve secrets again.
    """
    credentials = invocation.get("resource_binding", {}).get("profile", {}).get("credentials")
    if not credentials:
        return {}
    if not (invocation["phase"] == "VERIFICATION" and invocation["executor"] == "LOCAL"
            and observation is not None):
        raise RequestValidationError("credential injection requires a bound local verification command")

    def credential_provider(observer):
        environment, redactor = resolve_credentials(credentials)
        return environment, redactor, CredentialObservation(observer, invocation["resource_binding"], redactor)

    return {"credential_provider": credential_provider}


def finish_command_observation(raw, command):
    """Settle resource reports and cleanup through the existing durable result.

    Cleanup warnings remain diagnostics, not product failures. Non-resource
    commands retain their original result/classification. Source-version checks
    remain at the controller's acceptance boundary, including after recovery.
    """
    if "resource_binding" in command:
        return finish_resource_observation(raw, command["resource_binding"], command["observation_root"])
    return raw


def recover_command_observation(command):
    """Recover only complete original evidence, without reallocation or replay.

    Missing or partial captures return None; the controller retains the existing
    unknown-effect handling. There is no fallback that dispatches or reselects
    capabilities. Necessary checks that were never dispatched remain the
    controller's responsibility under the original attempt and budget.
    """
    try:
        raw = CommandObservation.recover(command["observation_root"], command["command_id"], command["executor"])
    except (ValueError, TypeError) as exc:
        raise RequestValidationError("cannot recover command observation: " + str(exc)) from exc
    return None if raw is None else finish_command_observation(raw, command)
