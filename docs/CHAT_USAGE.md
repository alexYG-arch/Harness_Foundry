# Codex Chat usage

## GENERIC_REVIEWED_BUILD_ONLY

All new builds use the generic reviewed Build route. The old Start Package,
Candidate, epoch, delegation and legacy runtime production workflows were retired
by the user on 2026-09-20. They are not optional fallbacks. Natural language is
the user interface; the CLI is the engineering interface.

Before any build, read [the build-document policy](GENERIC_BUILD_PLAN.md).
Preserve clarification Q&A, save and display a versioned readable build document,
and wait for actual human confirmation of that displayed scope. No Program or
target directory before that decision. Background checks, old grants and complete
answers do not substitute for review. Core source checks, engineering and
read-only history inspection remain allowed.

After confirmation, follow [the Build CLI](GENERIC_BUILD_CLI.md): prepare the
Requirement/Plan, sources and independent checks; show exact runtime scope before
recording a real human approval. The host authenticates actual messages and
semantic scope. JSON actor fields do not authenticate anyone. Document review
alone is not runtime approval.

Use advance-build for bounded implementation, checking, repair and continuation,
and read-build for persisted generic context. Do not ask per-Workpack permission.
Do not silently alter requirements, checker criteria, model, paths or budget.

## TRUE_GATE_ONLY

Stop for user-owned missing decisions, document review, missing/expanded runtime
authority, material contract changes, expiry/revocation, irreversible effects or
unknown side effects. No old Freeze/Generate token loop or per-log Hash ritual.
Source changes and tests do not authorize target execution or release.

## Historical inspection

Use read-history with the explicitly identified closed authoring database and
program ID. It returns recorded snapshots as historical data, not valid current
grants or suggested next actions. Nonempty WAL is refused; do not checkpoint or
rewrite old data merely to inspect it. Generic REVISION_V1 data uses read-build.
There is no automatic historical migration or re-signing of old approval.

Legacy public commands return LEGACY_WORKFLOW_RETIRED without reading request
files or opening controllers. Private baseline modules and tests/legacy_cli.py
exist only for regression provenance; do not invoke them as a production bypass.
The generic bundle excludes them. Historical docs describe past behavior only.

## Source operation and evidence

Use version and the public source gate for current interfaces. Development
validate-core/project-core-evidence preserve the historical 41-capability
baseline, explicitly not generic public-route or release acceptance. verify-spec
checks the read-only historical sibling, not a dependency of generic builds.
New archives use the generic/committed release assemblers, not package-local.

Complete in-scope source implementation and checks continuously; do not add
“continue” gates. Report actual scope: plan checks and historical regressions do
not prove installed-Harness usability, a full PRD, or same-package release
acceptance. See [release readiness](RELEASE_READINESS.md).
