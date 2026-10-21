#!/usr/bin/env python3
"""Compare Generic behavior using fixed existing fixtures and independently loaded sources.

Engineering diagnostic only: temporary LOCAL processes, no model/service calls or
real targets. Each invocation loads one source tree. Keep fixture_root fixed to
compare old/new code; this deliberately does not import shared projection helpers.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time
import types
from unittest.mock import patch

SCENARIOS = (
    ("public_normal", "test_build_entrypoint", "BuildEntrypointTests", "test_public_commands_run_real_local_fixture_verify_and_resume_without_replay"),
    ("assertion_repair", "test_build_runtime", "BuildRuntimeTests", "test_actual_failed_checks_repair_then_accept_before_next_task"),
    ("infrastructure_failure", "test_build_runtime", "BuildRuntimeTests", "test_verifier_environment_failure_does_not_trigger_implementation_repair"),
    ("not_dispatched", "test_build_runtime", "BuildRuntimeTests", "test_one_attempt_recovery_not_dispatched_preserves_budget_and_ignores_new_handoff"),
    ("completed_capture", "test_build_runtime", "BuildRuntimeTests", "test_crash_after_complete_checks_recovers_acceptance_without_reexecution"),
    ("unknown_capture", "test_build_runtime", "BuildRuntimeTests", "test_crash_after_dispatch_without_observation_is_held_not_replayed"),
    ("remaining_checks", "test_build_runtime", "BuildRuntimeTests", "test_crash_after_one_case_resumes_only_remaining_checks"),
    ("resource_capture", "test_build_resources", "BuildResourceIntegrationTests", "test_completed_resource_capture_recovers_without_redispatch_or_double_budget"),
    ("cleaned_resource", "test_build_resources", "BuildResourceIntegrationTests", "test_product_copy_cleaned_result_recovers_without_rebuilding_deleted_copy"),
    ("partial_resource", "test_build_resources", "BuildResourceIntegrationTests", "test_product_copy_materialization_failure_is_durable_without_retry_or_dispatch"),
    ("revocation", "test_build_entrypoint", "BuildEntrypointTests", "test_public_revocation_has_auditable_decision_and_blocks_execution"),
    ("expiry", "test_build_runtime", "BuildRuntimeTests", "test_revocation_and_expiration_stop_without_workload"),
    ("budget", "test_build_runtime", "BuildRuntimeTests", "test_total_budget_stops_without_reset_on_new_controller"),
    ("accepted_invalidation", "test_build_runtime", "BuildRuntimeTests", "test_missing_accepted_output_invalidates_dependents_without_resetting_budget"),
    ("repair_replay", "test_build_runtime", "BuildRepairTests", "test_exact_replay_after_rebuild_and_expiry_never_invalidates_again"),
    ("undispatched_continuation", "test_build_runtime", "BuildRepairTests", "test_continuation_after_no_intent_recovery_repairs_producer_first"),
    ("idempotency", "test_build_entrypoint", "BuildEntrypointTests", "test_idempotent_record_replay_does_not_add_a_second_event"),
)


def select(mapping, keys):
    return {key: mapping[key] for key in keys if key in mapping}


def semantic_signature(view, events):
    """Literal independent projection; do not import implementation state helpers.

    Compare behavior, not random IDs, wall timestamps, PIDs, temp absolute paths,
    process duration or report bytes containing the random command ID. Artifact
    content identities remain compared. Ordered event types are not normalized.
    """
    result_keys = ("status", "reason_code", "exit_code", "timed_out", "workload_started",
                   "failure_kind", "failure_domain", "automatic_retry_allowed", "output_truncated")
    observed = []
    for row in events:
        payload = row["payload"]
        if row["event_type"] != "BUILD_COMMAND_OBSERVED":
            continue
        value = payload.get("result", {})
        observed.append({**select(payload, ("phase", "executor", "workpack_id", "case_id")),
            "result": select(value, result_keys),
            "cleanup": select(value.get("resource_cleanup", {}), ("status",)),
            "product_copy_validation": select(value.get("product_copy_validation", {}), ("status",)),
            "reports": len(value.get("resource_reports", [])),
            "network": value.get("effective_network_policy")})
    return {
        "event_types": [row["event_type"] for row in events],
        "revision": view["stream_revision"], "writes_performed": view["writes_performed"],
        "attempts": [{**select(row, ("workpack_id", "status", "phase", "implementation_observation_status")),
                      "recovery_action": row.get("recovery", {}).get("next_action"),
                      "artifacts": {key: select(item, ("path", "sha256", "size"))
                                    for key, item in row.get("artifacts", {}).items()}}
                     for row in view["attempts"]],
        "authorizations": [{"state": row["state"], "budget": row["budget"]}
                           for row in view["authorizations"]],
        "observations": observed,
    }


def read_fixture(fixture, database=None):
    from harness_foundry_factory.build_entrypoint import read_build
    from harness_foundry_factory.revision_store import RevisionControlEventStore
    database = database or fixture.store.database_path
    store = RevisionControlEventStore(database, read_only=True)
    events = store.list_events(fixture.program)
    if not events:
        return None
    before = Path(database).read_bytes()
    view = read_build(database, fixture.program)
    again = read_build(database, fixture.program)
    assert view == again, "read-build must be stable"
    assert before == Path(database).read_bytes(), "read-build must not change expired/unfinished history"
    return semantic_signature(view, events)


def load_resource_fixture(fixture_root, source_root):
    """Move only private fault-injection addresses; fixture assertions stay fixed.

    A2 moved two resource operations from runtime to lifecycle. The same failure
    must be injected at their new owning module, rather than retaining dead hooks
    in production solely to satisfy tests. Original fixture bytes are unchanged.
    """
    path = fixture_root / "tests/test_build_resources.py"
    source = path.read_text()
    changes = {}
    if (source_root / "src/harness_foundry_factory/build_resource_lifecycle.py").exists():
        replacements = {
            "harness_foundry_factory.build_runtime.finish_resource_observation":
                "harness_foundry_factory.build_resource_lifecycle.finish_resource_observation",
            "harness_foundry_factory.build_runtime.materialize_product_copy":
                "harness_foundry_factory.build_resource_lifecycle.materialize_product_copy",
            "from harness_foundry_factory import build_runtime":
                "from harness_foundry_factory import build_resource_lifecycle as build_runtime",
        }
        for original, replacement in replacements.items():
            if original in source:
                changes[original] = {"replacement": replacement, "count": source.count(original)}
                source = source.replace(original, replacement)
    module = types.ModuleType("test_build_resources")
    module.__file__ = str(path)
    sys.modules[module.__name__] = module
    exec(compile(source, str(path), "exec"), module.__dict__)
    return changes


def run_scenarios(source_root, fixture_root):
    # The process must be fresh: old/new production modules may not share imports.
    if "harness_foundry_factory" in sys.modules:
        raise RuntimeError("run the baseline in a fresh Python process")
    sys.path[:0] = [str(source_root / "src"), str(fixture_root / "tests"), str(fixture_root)]
    support = importlib.import_module("test_build_runtime")
    hook_adapter = load_resource_fixture(fixture_root, source_root)
    rows = []
    for name, module, class_name, method in SCENARIOS:
        fixtures = []
        original_setup = support.BuildRuntimeTests.setUp
        def setup(fixture):
            original_setup(fixture)
            fixtures.append(fixture)
        case = getattr(importlib.import_module(module), class_name)(method)
        started = time.monotonic()
        try:
            with patch.object(support.BuildRuntimeTests, "setUp", setup):
                case.setUp()
                getattr(case, method)()
                states = [read_fixture(case.f, case.database)] if hasattr(case, "database") else [read_fixture(f) for f in fixtures]
                rows.append({"name": name, "test": f"{module}.{class_name}.{method}", "status": "PASS",
                             "signature": [state for state in states if state is not None],
                             "elapsed_seconds": round(time.monotonic() - started, 6)})
                case.tearDown()
        finally:
            case.doCleanups()
    return rows, hook_adapter


def compare(left, right):
    """Require the identical scenario contract and fixture bytes for comparison."""
    if left["fixture_files"] != right["fixture_files"]:
        raise ValueError("fixture source differs; behavior comparison requires fixed fixtures")
    old = {row["name"]: row["signature"] for row in left["scenarios"]}
    new = {row["name"]: row["signature"] for row in right["scenarios"]}
    if old != new:
        changed = sorted(name for name in old.keys() | new.keys() if old.get(name) != new.get(name))
        raise ValueError("behavior changed: " + ", ".join(changed))
    return {"status": "MATCH", "scenarios": len(old),
            "old_elapsed_seconds": sum(row["elapsed_seconds"] for row in left["scenarios"]),
            "new_elapsed_seconds": sum(row["elapsed_seconds"] for row in right["scenarios"]),
            "performance_claim": "LOCAL_FIXTURE_SAMPLE_ONLY_NOT_MODEL_OR_PRODUCTION_BENCHMARK"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--fixture-root", type=Path, required=True)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fixture_files = {str(path.relative_to(args.fixture_root)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in sorted((args.fixture_root / "tests").rglob("*.py"))}
    scenarios, hook_adapter = run_scenarios(args.source_root.resolve(), args.fixture_root.resolve())
    payload = {"schema_version": "1.0", "source_root": str(args.source_root.resolve()),
               "fixture_root": str(args.fixture_root.resolve()), "fixture_files": fixture_files,
               "scope": "ISOLATED_ENGINEERING_FIXTURES_NO_NATIVE_OR_REAL_MODEL_CLAIM",
               "hook_adapter": hook_adapter, "scenarios": scenarios}
    if args.compare:
        payload["comparison"] = compare(json.loads(args.compare.read_text()), payload)
    with args.output.open("x") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps({"status": "PASS", "scenario_count": len(payload["scenarios"]),
                      "comparison": payload.get("comparison"), "output": str(args.output)}))


if __name__ == "__main__":
    main()
