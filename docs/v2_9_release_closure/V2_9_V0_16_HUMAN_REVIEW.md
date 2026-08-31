# Harness Foundry v2.9 v0_16 Human Review

## 1. Review verdict

- Candidate: `Harness_Foundry_v2_9_Start_Package_Candidate_v0_16`
- Candidate content SHA-256: `e7223b8415bc70138e66ce4a35695344e707665824851100ae2106dbd73eb6a6`
- Factory state at review: `CANDIDATE_READY_FOR_HUMAN_REVIEW`
- Factory revision at review: `117`
- Factory Validator: `21/21 PASS`
- standalone self-check: `PASS`
- randomized-root relocation self-check: `PASS`
- Runtime, Driver, Workpack, install, publication and certification: `NOT_STARTED`
- Human Review verdict: `BLOCK_HUMAN_GATE`

The Candidate is portable and structurally consistent, but a direct adversarial
review proves that the active Epoch 2 final-release join can accept malformed,
cross-instance and non-hash-bound lane receipts as `RELEASE_READY`. The green
validators therefore do not yet establish the frozen CORR-29-012 semantics.

## 2. Blocking finding HR-V016-001: Closure Lane receipt validation is not enforced

Severity: `P0 / RELEASE_BLOCKING`

The frozen `CLOSURE_RECEIPT.schema.json` requires:

- `schema_version`;
- `lane_id`;
- `status`;
- `authority_scope`;
- `instance_id`;
- `creates_authority=false`;
- a 64-character lowercase hexadecimal `receipt_sha256`.

The production `evaluate_final_release` implementation checks only:

- the lane ID is one of Product, Safety or Release;
- the lane ID is not duplicated;
- `creates_authority` is false;
- `status` is `CLOSED`;
- `receipt_sha256` is a string.

It does not validate the declared schema, does not recompute the receipt Hash,
does not require all receipts to have one `authority_scope` and `instance_id`,
and does not bind the compatibility-linkage result to that same instance.

### Reproduced adversarial results

All three cases incorrectly returned `RELEASE_READY`:

1. each receipt omitted `schema_version`, `authority_scope` and `instance_id`,
   and used `receipt_sha256="x"`;
2. Product, Safety and Release receipts used three different `instance_id`
   values;
3. all receipts used `receipt_sha256="not-a-sha256"`.

Expected result for every case: fail closed with an explicit receipt-validation
or cross-instance-join error.

### Required correction

The replacement producer must generate and bind a final-release join that:

1. validates every receipt against the exact Candidate schema;
2. recomputes a canonical receipt body Hash rather than trusting a supplied
   string;
3. requires the exact same Program/authority scope, instance ID, Requirement
   Epoch, semantic contract identity and authorization risk identity across all
   three lanes;
4. binds the compatibility-linkage receipt to the same instance and identities;
5. rejects missing fields, wrong Hash format, body/Hash mismatch, stale receipt,
   duplicate lane, cross-instance receipt and mixed-epoch receipt;
6. adds these negative cases independently to standalone self-check and Factory
   Validator coverage.

## 3. Blocking finding HR-V016-002: CORR-29-009 is declarative, not executable

Severity: `P1 / HUMAN_GATE_BLOCKING`

CORR-29-009 requires three separate identities:

- Semantic Contract Identity;
- Implementation Release Identity;
- Authorization Risk Identity.

Its Coverage row declares `MATERIALIZED_AND_HASH_BOUND`, but its only
implementation references are the Epoch 2 Manifest and a JSON contract. The
active Runtime Module inventory contains recovery, complexity, closure and
projection modules, but no identity derivation or implementation-rebinding
module.

The replacement Candidate should add a deterministic identity implementation
and schemas that:

- derive each identity from its frozen field set;
- classify an implementation-only change separately from semantic/risk change;
- require a new machine grant for exact implementation bytes;
- require a new Human Gate only for semantic or authorization-risk change;
- reject omitted identity dimensions, stale current-state Hash and cross-scope
  reuse.

## 4. Blocking finding HR-V016-003: Complexity machine outputs have no exact contracts

Severity: `P1 / HUMAN_GATE_BLOCKING`

`COMPLEXITY_GOVERNOR.json` declares five machine outputs:

- `COMPLEXITY_BASELINE`;
- `COMPLEXITY_DELTA`;
- `RETIREMENT_MANIFEST`;
- `HUMAN_COST_RESULT`;
- `CIRCUIT_BREAKER_DECISION_RECEIPT`.

The Candidate provides only one generic complexity decision schema and the
implementation returns a decision, reason, violations and circuit-breaker flag.
It does not materialize exact schemas or a reconstructable binding for the
declared baseline, delta, retirement and Human Cost outputs.

The replacement Candidate should either:

- define and hash-bind each declared output schema and make the evaluator emit
  the exact structures; or
- replace the five-name declaration with one explicit aggregate receipt whose
  schema losslessly contains baseline, delta, retirement, Human Cost and
  circuit-breaker evidence.

Validator and standalone tests must reject a declared-output/runtime-output
mismatch.

## 5. Why the two green validators missed the problem

The standalone self-check tests a valid three-lane receipt set and a missing-lane
case, but does not test malformed Hashes or cross-instance joins. The Factory
Validator statically checks function names and semantic tokens but does not
independently exercise receipt validity and join identity constraints.

This is an oracle-depth problem, not a disagreement between the two validators:
both currently agree on an incomplete acceptance rule.

## 6. Preserved state and non-claims

- Candidate v0_16 was not modified by this review.
- Candidate v0_15 remains unchanged.
- Execution Project v0_7 and its failure report remain unchanged.
- Execution Root v0_16 does not exist.
- Human Gate was not consumed.
- No authorization, Driver, Workpack, transition, installation, publication or
  certification was created or executed.

## 7. Recommended next controlled transition

Do not approve the v0_16 Start Package Human Gate. If the user agrees, explicitly
REOPEN v0_16 and author a replacement v0_17 Candidate that closes HR-V016-001
through HR-V016-003. Preserve v0_16 and this report as read-only review evidence.
