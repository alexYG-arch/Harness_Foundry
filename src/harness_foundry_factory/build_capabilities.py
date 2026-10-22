"""Versioned capability descriptions, not a registry of permissions or dispatchers.

Pure descriptions can be read without loading a receiver, SDK, tool or database.
Unlisted needs remain valid project requirements; actual use follows the existing
reviewed scope and independent checks. No controller imports this catalog.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json


@dataclass(frozen=True)
class Capability:
    capability_id: str
    purpose: str
    input_shape: str
    implementation_modules: tuple[str, ...]
    dependencies: tuple[str, ...]
    unsupported_combinations: tuple[str, ...]
    factory_knowledge: str
    factory_execution: str
    target_delivery: str
    acceptance_boundary: str
    protocol_versions: tuple[str, ...] = ("2.9",)


CAPABILITIES = (
    Capability("temporary-files", "Checker temporary files and caches",
        "verification_resources.profiles.<id>: writable_areas, report_files, retention",
        ("build_resource_lifecycle", "verification_resources", "resource_observation"), ("Declared LOCAL checker",),
        ("Cross-command persistent sidecars",),
        "Scratch is an optional verification need.", "Per-command scratch and report staging.",
        "Does not add temporary storage to the target automatically.",
        "Cleanup follows durable collection; failure retention is not a product assertion."),
    Capability("sqlite", "Checker-owned SQLite, including transaction/WAL files",
        "Use a database path under the declared resource scratch area",
        ("verification_resources",), ("temporary-files", "Python sqlite3 or the selected SQLite tool"), (),
        "SQLite verification use and target database requirements are separate.",
        "Ordinary local file access; no database engine or server is installed by Foundry.",
        "A target database needs its own declared implementation and contract.",
        "File permission support does not prove the target's transaction semantics."),
    Capability("local-service", "Finite checker-owned Unix and/or loopback service",
        "network={mode:LOCAL_SERVICE,tcp:LOOPBACK,unix_sockets:[resource://scratch/...]} (declare one or both selectors)",
        ("resource_network", "verification_resources", "coding_process"),
        ("temporary-files", "Native Codex receiver"),
        ("LOCAL_SERVICE and REMOTE_SERVICE in the same command", "Cross-command sidecars"),
        "Choose only if the check needs a local service.",
        "Explicit exact Unix paths and/or loopback TCP and UDP on all ports; native DNS exception may remain.",
        "A delivered service is a separate target component or external binding.",
        "The TCP selector is not TCP-only or per-service isolation; service ownership and cleanup remain checker duties."),
    Capability("remote-http", "Necessary remote HTTP(S) verification requests",
        "network={mode:REMOTE_SERVICE,allowed_hosts:[exact hostname or IP]}",
        ("resource_network", "coding_process"), ("Native Codex network proxy",),
        ("REMOTE_SERVICE and LOCAL_SERVICE in the same command", "Direct arbitrary networking"),
        "Match the actual service and host need, not a task category.",
        "Native proxy host allowlist; it does not constrain ports or operations.",
        "Target client, endpoint and account binding are explicitly selected separately.",
        "A catalog entry does not establish account access or successful service acceptance."),
    Capability("test-credentials", "Credentials for one declared verification command",
        "verification_resources.profiles.<id>.credentials={ALIAS:{ref:env:VARIABLE,purpose:...}}",
        ("resource_credentials", "resource_observation"), ("Declared host credential source",),
        ("Automatic injection into CODEX implementation or unrelated commands",),
        "Authentication need does not imply a cloud service.",
        "Resolve for the bound LOCAL check and redact known values from controlled outputs.",
        "Does not copy credentials or a credential SDK into the delivered target.",
        "Injection and controlled-output filtering do not constitute a successful real-account test."),
    Capability("product-copy", "Writable working copy for tools generating in-project files",
        "verification_resources.profiles.<id>.product_copy={files:[relative input],writable_paths:[relative generated directory]}",
        ("verification_resources", "verification_snapshot", "resource_observation"),
        ("temporary-files", "Declared product source files"),
        ("Implicit whole-repository copy", "Accepting a result after declared source inputs changed"),
        "Select only when a check needs project-local writes.",
        "Copy declared input files, bind source versions, archive results and clean successful copies.",
        "The copy is a verification resource, not the accepted target version.",
        "Checks cover declared input versions; undeclared files are not silently added."),
    Capability("composition-upgrade", "Assemble or update target components while preserving customizations",
        "Ordinary composition, G/A/C/N inputs and explicit file apply descriptions",
        ("build_entrypoint", "build_runtime"),
        ("examples/harness-composition-upgrade/helpers/merge.py",
         "examples/harness-composition-upgrade/helpers/apply.py",
         "examples/harness-composition-upgrade/helpers/file_states.py"),
        ("Helper diagnostics as controller acceptance", "Byte-comparison helper resolving semantic conflicts", "Helper-level multi-file transactions"),
        "Component examples are reuse references, not a closed whitelist.",
        "Existing reviewed CODEX/LOCAL route; helper code stays outside the execution core.",
        "Select actual project components, workflows and tools from requirements.",
        "The outer session preserves A/G references after acceptance; packaging examples is not S4 business acceptance."),
    Capability("business-workflows", "PRD/design, data reasoning and market research examples",
        "Group manifest plus v1/v2 workflow, original inputs, independent expected values and host evidence",
        ("build_entrypoint",),
        ("examples/harness-composition-upgrade/integration/business_requests.py",
         "examples/harness-composition-upgrade/verifier/check_business.py",
         "Explicit host browser/search tools when required"),
        ("Chat tools implicitly inherited by a CODEX subprocess", "Fixed sources as proof of live retrieval"),
        "Business requirements and missing tools are analyzed for the selected task.",
        "Existing automatic production then independently reviewed LOCAL reuse.",
        "Actual workflows and external tool bindings belong to the target/host delivery.",
        "Structured checks do not prove visual, semantic or live-search quality; real host evidence is separate."),
)


def describe_capabilities(capability_id=None):
    """Return copyable descriptions without making a selection or authorizing use."""
    selected = [item for item in CAPABILITIES if capability_id is None or item.capability_id == capability_id]
    if not selected:
        raise KeyError(capability_id)  # Unknown to this small catalog, not a forbidden requirement.
    return {"catalog_version": "R3-1", "target_protocol_version": "2.9",
            "descriptive_only": True, "execution_authority_granted": False,
            "acceptance_claimed": False, "capabilities": [asdict(item) for item in selected]}


def render_reference():
    lines = ["| Capability | Inputs | Runtime modules | Dependencies | Known unsupported combinations |",
             "|---|---|---|---|---|"]
    for item in CAPABILITIES:
        lines.append("| " + " | ".join((item.capability_id, "`" + item.input_shape + "`",
            ", ".join(item.implementation_modules), "; ".join(item.dependencies),
            "; ".join(item.unsupported_combinations) or "None declared here")) + " |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", help="Describe a known capability; unknown is not a policy denial")
    parser.add_argument("--markdown", action="store_true", help="Print the static reference table")
    args = parser.parse_args(argv)
    if args.markdown:
        print(render_reference(), end="")
        return 0
    try:
        result = describe_capabilities(args.id)
    except KeyError:
        print(json.dumps({"status": "NOT_DESCRIBED", "capability_id": args.id,
            "execution_authority_granted": False, "requirement_disallowed": False}))
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
