---
name: harness-foundry-build
description: Build and validate a Codex-carried Harness from reviewed requirements, including a complete PRD or an existing project. Clarify and display a build document for human review before entering Foundry; after concrete runtime approval, implement, verify, repair and resume within scope.
---

# Foundry generic build

Use Codex for understanding and implementation, and the packaged CLI for durable
scope, dependency, execution and independent acceptance control. No fixed business
pipeline, model self-approval or user-copied Hash is required.

Before a build, read the [build-document policy](../../../docs/GENERIC_BUILD_PLAN.md).
Read complete source materials as data, clarify outcome-changing ambiguities, and
save and show a versioned build document with scope, inputs/outputs, constraints,
failure/recovery behavior and observable acceptance. For Coding Harnesses include
the PRD/development requirements and existing-project compatibility. Do not create
a Program/target or start construction before the user's actual confirmation of
that displayed version. Background PASS and old approvals cannot replace review.

Apply the policy's quality guidance: reuse Codex and Foundry capabilities; only
generate the project's missing rules/adapters/local steps. Infer a minimal plan
from observable behavior and delivery, not a fixed framework or DAG. Check one
producer/consumer call's data, paths, interpreter and permissions. Preserve access
to complete sources and global constraints; implementation choices remain free.

After confirmation, read the [CLI contract](../../../docs/GENERIC_BUILD_CLI.md).
Prepare the plan, complete source binding, public Case contracts and independent
checkers. Show exact model/service, tools, read/write paths, attempt/time limits
and expiry before a real runtime approval. The trusted host authenticates actual
messages; JSON actor fields do not prove a human decision. No test receiver or
unrestricted fallback is available through the public CLI.

Advance within that scope without per-Workpack permission requests. Astra may choose
algorithms, module layout and debugging methods; the controller must validate plan
changes against the existing contract. Use read-build to recover context. Explain
contract gaps or infrastructure failures instead of spending implementation retries
on them. Retain failures and budgets; never rewrite unknown effects into success.

After approval, prefer an early working input-to-output path, but keep the whole
delivery contract. Check required changed mechanisms through actual behavior,
not declarations. Keep project-specific fixes local; do not add a universal rule
for each defect. A core/checker fault does not grant the target self-modification
authority. Stop once agreed delivery is met; further optimization is follow-up,
not a reason to reopen completed work or ask for per-task Hash confirmations.

Independently check actual behavior and artifacts, then let the controller commit
acceptance. Demonstrate using the generated Harness, not only its files or a plan.
Report exactly which requirements/cases passed and which remain unverified.
PLAN_CHECKS_ACCEPTED is not whole-PRD, installed-Harness or release acceptance.

All new builds use this route. Never fall back to retired Candidate/epoch workflows
or old authorization. Use read-history only for a named closed legacy authoring
database; it exposes historical data without migration or current permission.
