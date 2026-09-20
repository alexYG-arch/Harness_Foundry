# Harness Foundry — generic Codex runtime

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

Public sample inputs: [complete Task CLI PRD](examples/task-cli/PRD.md) and
[existing CSV project](examples/csv-increment/PROJECT_BRIEF.md), with its starter
code and tests. They are synthetic examples, not pre-approved builds or embedded
business logic. Every real use still requires document review and runtime approval.

## Compatibility and acceptance

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
meets its requirements. Formal release needs the declared same-package new-project
and existing-project acceptance evidence, plus closure of known in-scope defects.
Use a separate directory for an upgrade; code rollback does not undo effects,
revive authorizations or permit silent database downgrades.

MIT license: [LICENSE](LICENSE). Canonical source and issue reporting:
[alexYG-arch/Harness_Foundry](https://github.com/alexYG-arch/Harness_Foundry).
Do not publish credentials, private requirements or raw runtime data in issues.
