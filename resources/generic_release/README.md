# Harness Foundry — generic Codex runtime

Product version **0.5.0**; protocol **2.9**. This is a release-preparation candidate.
It adds declared verification resources, protected product copies, controlled repair
and single-attempt handoff. Existing published releases remain unchanged.

Open this directory as a Codex project. Its local `harness-foundry-build` Skill
guides a build from clarified requirements and a human-reviewed build document.
Codex performs reasoning and coding; local deterministic stages and independent
checks are controlled by the same approved scope. No private author workspace,
specific business pipeline or external normative sibling is part of this runtime.

## Start without running a target

Requires Python 3.11+; the generic runtime has no third-party Python dependency.

```bash
python3 tools/hffactory.py version --json
python3 tools/hffactory.py --help
```

Describe the Harness goal and provide complete requirements/project materials.
Foundry first displays a versioned build document for your review; it must not
start construction merely because all questions or automatic checks are satisfied.
After confirmation it presents a separate bounded runtime scope. That approval
covers in-scope execution, checking, repair and resume, not publication or expansion.
No account tokens or author configuration are bundled. Use your own legitimate
Codex login. Native execution currently targets POSIX hosts and requires explicit
Codex executable, model/service, local tool and instruction-read bindings; a
Python import smoke is not native sandbox acceptance. No silent model fallback.

On macOS, do not put this runtime, inputs, verifier, controller or target in shared
`/tmp` (including its `/private/tmp` alias). The current native receiver did not
enforce read-only protection there in an offline probe. Foundry rejects that
layout before dispatch with `SHARED_TEMP_ISOLATION_UNSUPPORTED`; this is a support
restriction, not a fix to the underlying Codex sandbox. Use an independent ordinary
project directory and check the actual native read/write boundaries before a run.

The agent prepares public CLI requests following [Build CLI](docs/GENERIC_BUILD_CLI.md),
[Plan](docs/GENERIC_BUILD_PLAN.md), [sources](docs/GENERIC_SOURCE_INTAKE.md),
[acceptance contracts](docs/ACCEPTANCE_CONTRACT_ALIGNMENT.md) and
[runtime](docs/GENERIC_BUILD_RUNTIME.md). You do not need to hand-write internal JSON.
The existing revision SQLite control store remains authoritative; it must stay
outside all target write roots. Neither plans nor model output grant authority.

Public sample inputs: [complete Task CLI PRD](examples/task-cli/PRD.md),
[existing CSV project](examples/csv-increment/PROJECT_BRIEF.md), with its starter
code and tests, and the [verification resources example](examples/resource-check/README.md). They are synthetic examples, not pre-approved builds or embedded
business logic. Every real use still requires document review and runtime approval.

The [static capability reference](docs/CAPABILITY_REFERENCE.md) separates factory
knowledge, execution support and target delivery. It is descriptive, not an
execution allowlist. The [composition/upgrade examples](examples/harness-composition-upgrade/README.md)
include two mechanism fixtures and three business workflow preparations with their
helper and checker dependencies. Their presence does not establish live business
or complete Harness acceptance.

Optional [capability preparation helpers](examples/capability-adapters/README.md)
support explicitly selected, separately supplied capability versions. They resolve
host bindings and prepare tool calls; they do not install packages or execute them.
The Foundry observation adapter is included here; its optional public dashboard
component is selected separately. Projects without these components keep the same
reviewed build route.

## Verification resources and repair

Declare resource profiles only when checks need scratch/cache files, SQLite, owned
local services or HTTP(S) calls through a host allowlist. Keep the offline NONE
mode for checks that need no network. An explicit product copy supports tools that
write generated files inside their project without writing the original product.
The checker and its declared judgment dependencies run from protected copies.
Optional test credentials reach only their bound local verification command; known
values are filtered from controlled logs and declared archived reports. Saved
results support recovery without replay, and successful per-command resources are
cleaned after the result is durable. Read the exact permissions and lifecycle in
[Build CLI](docs/GENERIC_BUILD_CLI.md) before selecting a profile.

The outer Codex session confirms extra findings, merges relevant history and decides
whether another repair is useful. The Harness preserves its independent checks and
budgets. Use the controlled repair entry for eligible accepted producers and optional
ONE_ATTEMPT handoff when the outer session needs to decide before the next dispatch.
Diagnostic progress may justify another attempt even without a code change.

## Compatibility and acceptance

Human-facing dialogue and documents follow the [clear communication policy](docs/CLEAR_COMMUNICATION.md).
For an existing generic Program, `python3 tools/hffactory.py read-build --control-db DB --program-id ID --human`
shows a Chinese, read-only status summary. Substitute your existing absolute database path and Program ID.
The default JSON output and `--json` interface are unchanged; `--human` and `--json` cannot be combined.
The summary does not grant authority, start tasks or replace full scope/evidence review.
Runtime prompts embed the same policy and carry it into declared Harness guidance
outputs, without Foundry-local links, extra read/write permissions or approval gates.
This does not retroactively update existing projects or prove model writing quality.

This generic distribution intentionally omits historical Candidate/epoch commands,
fixed three-project protocols and domain-specific workflows. It does not migrate
or reopen old authoring databases. Existing REVISION_V1 generic control data keeps
its format; opening another format fails before rewriting it. Historical source
regressions are retained in the development repository, not shipped as executable
compatibility routes. The old 41-capability baseline is not a certification of this
distribution. See PACKAGE_MANIFEST.json for product identity and packaged commands.

For a closed historical authoring database, read-history --database DB --program-id
ID returns only the original snapshot as historical data. It does not migrate,
replay or authorize it; nonempty WAL is refused rather than ignored. Use read-build
for generic revision data. The developer checkout also retires old new-build routes.

Validate and use the exact archive intended for delivery. A package inventory,
archive checksum or successful CLI command is not evidence that a target Harness
meets its requirements. Complete release acceptance needs the declared same-package
new-project and existing-project evidence, plus closure of known in-scope defects.
This candidate does not itself assert publication or CI success. Its final validation
and release information will identify the selected commit and exact archive.
Existing tags and archives remain available from
[published releases](https://github.com/alexYG-arch/Harness_Foundry/releases).
This engineering candidate does not replace a published release.
Use a separate directory for an upgrade; code rollback does not undo effects,
revive authorizations or permit silent database downgrades.

MIT license: [LICENSE](LICENSE). Canonical source and issue reporting:
[alexYG-arch/Harness_Foundry](https://github.com/alexYG-arch/Harness_Foundry).
Do not publish credentials, private requirements or raw runtime data in issues.
