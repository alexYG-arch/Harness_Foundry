# Epoch 28 semantic repair loop

Status: semantic-family repairs and the opt-in delegation extension are tested;
the epoch 28 Candidate remains immutable and unapproved. A replacement epoch 29
has been generated and reviewed under the explicit delegation, as recorded in
[the epoch 29 review](FOUNDRY_EPOCH29_DELEGATED_REVIEW_20260906.md). This plan does
not execute target Workpacks, Driver, or Harness.

## Evidence and design

The read-only review proved three reachable contract defects: a phase mutation
outside the first object is invisible to the declared evaluator inputs; the
sync mutation necessarily also breaks phase interval equality; registry cases
with same-Job dependencies have no corresponding read lease route.

Research consulted on 2026-09-06:

- [MLIR ODS](https://mlir.llvm.org/docs/DefiningDialects/Operations/) centralizes
  operand and constraint definitions and separates structural and custom
  verification. Application here: a registered ordered-phase interval operator
  over complete per-subject arrays, not an untyped algorithm name or mutation
  seed used as the evaluation domain.
- [Hypothesis stateful testing](https://hypothesis.readthedocs.io/en/latest/stateful.html)
  distinguishes rule preconditions from invariants checked after each step.
  Application here: independently check the coupled timing constraints after
  the declared mutation, and require the predeclared failure closure.
- [LLVM issue 211581](https://github.com/llvm/llvm-project/issues/211581) reports
  a verifier crash on missing operands. It is an upstream reproduction, not
  evidence of a Foundry defect. It reinforces testing invalid operator
  signatures before evaluation; no new security layer is inferred from it.

## Bounded engineering sequence

1. Add independent regression witnesses before implementation: all object/phase
   positions, interval boundaries, and a generic non-video phase vocabulary.
2. Repair the Producer declaration, typed evaluator, independent semantic
   validator, and exact known legacy projection migration together.
3. Declare timing mutation dependencies by artifact kind, check the actual
   changed constraint set, and update all contradictory Lab text projections.
4. Bind registry schema instances to their same-Job dependency read closure,
   reusing the existing lease protocol without granting Job writes.
5. Run focused and full regressions, spec/skill/core checks, then independently
   inspect generated output and migration/idempotence against the frozen IR.
6. Continue any newly demonstrated reachable defects through the same sequence.
   Passing source tests alone does not prove a replacement Candidate ready.

No digest, authorization, runtime dependency, or new governance stage is added
to close these three defects. Pre-build delegation must remain distinguishable
from an exact human confirmation; no human token or decision is fabricated.

## Iteration 1 evidence

- Added 8 phase/timing and 5 registry-read test methods. Phase tests exercise
  every phase of every object in a 3-shot/3-object witness, all interval
  endpoints, two-phase non-video vocabulary, short HOLD boundaries, legacy
  migration, and independent rejection of truncated projections.
- The registered `ORDERED_PHASE_INTERVAL_PARTITION_V1` consumes each subject's
  complete segment array and boundary vector. The interpreter has no dispatch
  on a video invariant ID. Producer and independent Validator both bind the
  complete domain; no exception converts a malformed primitive to external work.
- Timing failure closures are consumer-kind scoped and follow the changed
  timing fields. Independent arithmetic demonstrates the sync/phase coupling;
  a short HOLD adds the enter/hold-order failure already declared in the closure.
- Registry routing now emits schema-bound transitive read plans and sequential
  per-Job leases, with no Job writes. The reference callback loader proves
  release-on-error and no overlapping active leases. This is Factory contract
  testing, not target Lab execution.
- Temporary Candidate integration proves the emitted plans fit declared read
  scopes and removal of a partition is independently rejected. The formal
  epoch 28 directory was not edited.
- Full suite: **494 tests PASS in 438.534 seconds**, 0 failures/errors.
  `verify-spec` (101 files), `validate_skill`, `validate-core`, and
  `git diff --check` also PASS.
- Frozen epoch 28 IR was recompiled entirely in memory: 74 artifacts, 74
  schema read plans, independent invariant findings empty, Registry consistent,
  independent read plans equal, compilation idempotent, original IR unchanged.

## Iteration 1 follow-up: aggregate baseline cycle (repaired in iteration 2)

The above green suite is not a claim of overall readiness. A subsequent
read-only acquisition-graph check found the new live-input plan is insufficient
for the aggregate's own tests:

- `ART-ATOM-THREE-FIXTURES-LAB-CERTIFICATION` is selected as a shared base input.
- Its final receipt requires 806 Case result refs, including 27 registry Cases
  that test the aggregate's own schema/invariants.
- Requiring that final receipt as their passing base creates a cycle. This was
  not covered by the previous read-permission tests. Do not publish a new epoch
  from this source state or call the third finding fully closed.

The resulting iteration 2 scope was to add the failing acquisition-cycle regression,
separate isolated test baseline fixtures from live certification artifacts, and
review whether evidence validation is incorrectly also being used to execute
the tests it validates. The last point is a hypothesis to verify, not a proven
additional defect. Preserve full schema/Oracle validation and all actual Case
execution evidence requirements; do not resolve this by excluding the aggregate
Cases, weakening their predicates, or inventing successful receipts.

[Pact provider states](https://docs.pact.io/getting_started/provider_states)
requires isolated verification contexts and provides explicit setup of test
preconditions. [pytest fixtures](https://docs.pytest.org/en/stable/explanation/fixtures.html)
separates setup errors from test failures. These inform the next design, not
proof that a Foundry fix already exists. The baseline namespace must be
explicitly non-certifying, with no ability to substitute synthetic data for
the live certification result set.

## Iteration 2: isolated baselines and finite evidence consumers

Engineering evidence, not target Lab execution or Candidate approval:

- Two new tests first reproduced the live aggregate acquisition and its
  transitive-consumer variant. The read planner now partitions artifacts by
  their declared Case-result dependencies, not by video or aggregate kind.
  Case-dependent artifacts and their consumers become fixture inputs; unrelated
  live Job inputs retain the existing sequential read leases.
- Producer and independent Validator emit/check `fixture_artifacts`, explicit
  `ISOLATED_CONTRACT_FIXTURE` context, and a Case/schema-specific
  `baseline_root_ref`. All original result refs remain required. The existing
  partition-aggregation policy is explicitly scoped to Acceptance/Negative
  Cases; Registry Cases use their declared sequential read protocol.
- The reference fixture preparation helper has no filesystem, Case runner, or
  live fallback. It preserves captured input bytes, prevents Candidate/input
  reference overrides, checks every base/fixture through the required validator
  callback, and distinguishes setup errors from negative-test success.
  Its test context refuses runtime-evidence resolution. This helper is not a
  general fixture synthesizer or an implementation of the target Lab.
- Confirmed the second half of the cycle: the old aggregate predicate required
  replaying the Cases it summarized. Replaced both aggregate mutation predicates
  with registered `REGISTRY_MUTATION_RESULT_EVIDENCE_V1`. It reads finite result
  records, checks exact Case/schema membership, outcomes, allowed failure sets,
  and equality to referenced result-byte projections. It never invokes a runner,
  mutation, or recursive baseline verification. Existing digest predicates remain
  mandatory; this semantic predicate introduces no new digest computation.
- Known old projections migrate to the new operation; unknown structured
  overrides reject. Registry identity/schema/ref mutation closures now include
  this consumer. Dedicated witnesses demonstrate the newly declared dependency,
  rather than copying observed failure sets into a permissive whitelist.
- Added 11 test methods (4 read/setup and 7 finite-result tests); extended the
  temporary Candidate integration to check isolated bases and reject removed
  fixture plans. Related 44 tests PASS. Full suite: **505 tests PASS in 433.175
  seconds**, 0 failures/errors. `verify-spec` (101 files), `validate_skill`,
  `validate-core`, and `git diff --check` PASS.
- Recompiled frozen epoch 28 IR only in memory: 74 artifacts/schema plans;
  independent invariant findings empty; Registry consistent; independent read
  plans equal; repeated compilation idempotent; original IR unchanged. The one
  Case-dependent aggregate no longer appears among live shared inputs.
- A separate synthetic in-memory witness covers all 773 invariant schema
  instances and 9 schema-native instances from the actual frozen Registry.
  Their finite consumers perform 774 and 10 reads respectively (one Registry
  plus each result once), including the aggregate's own test definitions.
  These are predicate witnesses, **not** actual Case execution receipts.

At the end of iteration 2, overall readiness remained unproven. Iteration 3 below
addresses the standalone result and execution-evidence interface. A replacement
Candidate and its independent review remain outstanding. Neither these source
tests nor a synthetic baseline can prove real TTS, rendering, or Harness execution.

## Iteration 3: standalone Registry execution-result protocol

The new missing-evidence regression initially failed: a record containing only
passing outcome flags and its result bytes was accepted. This is an ordinary
result-interface gap, not a hypothetical hostile-supervisor scenario.

- Producer now publishes distinct Registry result and process-observation
  schemas covering INVARIANT and SCHEMA_NATIVE Cases. Each invocation binds the
  result schema and exact command receipt. Ordinary Acceptance/Negative schemas
  are not silently reused for incompatible Registry payloads.
- A local invocation supervisor observes the completed process, retains logical
  argv separately from Runtime-resolved argv, and records actual exit code and
  captured output. Printing PASS with exit code 2 cannot certify the Case.
  The reference observer does not launch a process or grant authority.
- The finite aggregate consumer binds results to the frozen execution manifest,
  command observation, and actual before/after input bytes. These three previously
  unbound byte references each have one digest consumer. No self-hash, signing
  service, repeated test execution, or recursive baseline validation was added.
- Result/receipt schemas, read protocol, Lab implementation obligations, exact
  legacy migration, Producer, and independent Validator were updated together.
  Unknown structured overrides still reject. Runtime verification uses only the
  standard library; jsonschema remains a test-only optional dependency.
- Added four test methods: missing proof, both schema kinds and non-certifying
  failures, actual small subprocess exit observations, and missing/mismatched
  process/input bindings. Extended the temporary Candidate integration to reject
  a removed receipt-schema requirement. This is Factory engineering validation,
  not execution of the target Lab, Workpacks, Driver, or Harness.
- Related 48 tests PASS. Full regression process completed with **509 tests PASS
  in 435.109 seconds**, zero failures/errors. Completion was collected from the
  existing process handle; the suite was not restarted merely because observation
  had yielded. Spec validation (101 files), skill validation, core validation, and
  git diff whitespace checks also PASS.
- A subsequent frozen-IR recompile, entirely in memory, reports 74 artifacts and
  74 read plans; independent invariant findings empty; independent read plans
  equal; Registry consistent; compilation idempotent; original IR unchanged.
  The declared matrix still contains 773 invariant schema instances and 9
  schema-native instances. These counts are coverage declarations, not Case
  execution receipts. Iteration 2's synthetic read counts precede this protocol.

Research checked against primary sources:

- [Bazel Test Encyclopedia](https://bazel.build/reference/test-encyclopedia): the
  observed test process outcome, not a printed PASS string, determines success.
  Applied here to the existing local supervisor boundary; Bazel itself and its
  broader environment policy are not introduced.
- [Pact provider states](https://docs.pact.io/getting_started/provider_states):
  verification inputs are prepared in isolated contexts. Applied to non-certifying
  fixture inputs, not as a replacement for actual execution-result observations.

## Candidate review versus source repair

A subsequent read-only review of the immutable epoch 28 Candidate reproduced
the original phase-selector omission and timing-mutation contradiction using
in-memory selector/arithmetic witnesses. It also confirmed missing Job read
routing, the aggregate replay self-dependency, and incomplete Registry result
bindings. Its recorded generation-time PASS is historical. The current working
Validator returns FAIL with overlapping findings, including new schema-contract
requirements; those messages are not counted as separate new root causes.

The source repairs above do not retroactively change the Candidate. At that
review point no formal replacement Candidate had been published or reviewed. Permission drift
remains non-blocking under the frozen personal-local policy.

## Formal state and authorization decision history

Before the explicit delegation was registered, the formal Program remained
epoch 28, revision 184, FROZEN and
CANDIDATE_READY_FOR_HUMAN_REVIEW; state hash remains
`e1bb3f39301c1524d52a01727076c6bf0a3824354c482c582f82157c8ddde33d`.
No Candidate approval, REOPEN, new output root, or target execution had occurred
at that historical decision point.

At the protocol-impact review, the Factory actor schema accepted only HUMAN_VIA_CODEX_CHAT, and Freeze
requires a later user turn with an exact token. The requested automatic
pre-build authorization is therefore not represented by its persisted protocol.
This was verified in Actor.from_value and FactoryService._confirm_freeze, rather
than inferred from an old state record.

The local authoring skill prohibits auto-submitting a human confirmation token.
Pinned v2.8 authorization section 4 also requires stopping after Candidate
authoring, and section 5 preserves initial Candidate approval as a human decision.
Its user-adjustment policy section 4 classifies changing this boundary as an
invariant-impacting request requiring an explicit impact decision. Automatic
source engineering is not the same action as changing those decision semantics.

That decision was subsequently approved explicitly by the user: “批准新增可审计的代理委托协议”.
The clarified scope includes pre-build Candidate review and approval; the earlier
proposal to retain a final Candidate human gate was not adopted. Actual Harness
construction/execution remains outside the grant. The new opt-in extension is
specified in [PREBUILD_DELEGATION_PROTOCOL.md](PREBUILD_DELEGATION_PROTOCOL.md).
It uses a separate delegated actor and decisions, not human confirmation tokens.
The pinned v2.8 snapshot remains read-only, and old human-path semantics remain
unchanged. Source implementation and temporary integration tests do not themselves
activate a delegation for the formal epoch 28 Program.
