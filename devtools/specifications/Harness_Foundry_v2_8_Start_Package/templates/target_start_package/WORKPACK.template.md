# Workpack: <WORKPACK-ID>

## Machine Metadata

- Schema Version: `2.8`
- Program ID: `<PROGRAM-ID>`
- Project ID: `<PROJECT-ID>`
- Result Ref: `<WORKPACK-RESULT-REF>`
- Promotion Ledger Ref: `PROMOTION_LEDGER.jsonl`

## Objective

<One bounded outcome.>

## Primary Layer Type

`<RULE_DEFINITION|MODULE_IMPLEMENTATION|RUNTIME_ORCHESTRATION|RELEASE_PACKAGING|TARGET_APPLICATION|CONFORMANCE_INTERFACE|CONFORMANCE_PACK|CONFORMANCE_LAB_MODULE|CONFORMANCE_LINKAGE_REVIEW|CONFORMANCE_REPAIR_ROUTING>`

## Preconditions

- Current phase state: `<STATE>`
- Required predecessor lock refs: `<REFS>`
- Required Atom IDs: `<ATOM-IDS>`
- Required source hashes: `<HASHES>`

## Execution Context

- Execution Mode: `<MODE>`
- Target Environment: `<ENV>`
- Authorization Ref: `<REF-OR-NOT-REQUIRED>`
- Auto-start generated Workpacks: `false`
- Controlled Auto-advance Eligible: `<true|false>`
- Maximum Authorized Attempts: `<INTEGER>`

## Scope

- Allowed Write Paths: `<PATHS>`
- Forbidden Write Paths: `<PATHS>`
- Required Inputs: `<INPUTS>`
- Expected Outputs: `<OUTPUTS>`

## Runtime and Evidence

- Primary Runtime: `<RUNTIME>`
- Runtime Attestation Requirement: `<POLICY-REF>`
- Command Manifest Ref: `<REF>`
- Capsule Ref and Hash: `<REF-AND-SHA256>`
- Required Stage/Runtime Receipts: `<REFS>`

## Preflight

- Verify exact predecessor Locks and reports.
- Verify Capsule, Workpack and Command Manifest hashes.
- Verify current authorization class, scope, expiry and remaining transition/loop budget.
- Stop on any open blocker, finding, invalidation, unknown state or undeclared command.

## Acceptance

- Positive cases: `<CASES>`
- Negative cases: `<CASES>`
- Boundary cases: `<CASES>`
- Required Evidence: `<EVIDENCE>`

## Forbidden Claims

- <What this Workpack cannot prove.>

## Loop and Repair

- Loop Policy Ref: `LOOP_POLICY.json`
- Loop State Ref: `<LOOP-STATE-REF>`
- Finding Schema Ref: `FINDING_SCHEMA.json`
- Repair Routing Ref: `REPAIR_ROUTING_RULES.json`
- Invalidation DAG Ref: `INVALIDATION_DAG.json`

Loop convergence does not equal Workpack PASS. A repeated finding, oscillation, scope change, new command or exhausted budget stops the loop and escalates.

## Done and Handoff

PASS requires Postflight, unresolved-gap routing, evidence binding and a validated `WORKPACK_RESULT.json`. PASS alone cannot activate the next Workpack. Only the Build Program Driver may append a promotion event and activate the single next eligible Workpack, and only when a current execution authorization explicitly permits controlled auto-advance. Human gates and real-target installation never auto-advance.
