# Qt / CMake environment adapter, version 2

This package connects explicitly selected native QtCore, CMake and CTest tools
to the existing Foundry build, independent-check and delivered runtime paths.
It preserves version 1. It does not install tools, grant permissions, retry,
call a model, schedule tasks or own attempt budgets.

The shared environment profile format is version 1, separately from package
`qt-cmake` version `2` and the observed Qt/tool versions. The helper interpreter
role is `qt-python`, so a target may use a different `python` virtual environment.
Tool invocation aliases are preserved; the selected SDK uses its resolved Qt
CMake metadata location. No package file contains a machine installation path.

## Bind, observe and verify

Selected dependency observations retain symbolic-link facts in `extensions.path_aliases` and propose the real parent directories needed to inspect those links in `read_paths`. This follows selected load paths only, without scanning an installation. Some receivers canonicalize exact link grants; a parent-directory read can expose directory names and link metadata, so the host must review that actual scope and verify unrelated targets remain unreadable. The proposal never grants permission. Reuse checks the recorded links again; changed targets require a relevant probe and unavailable observations remain UNKNOWN. Bind a real dependency-query executable, or its explicitly declared launcher dependencies, when a tool entry is a forwarding shim.


Use explicit absolute paths in the following commands. They are placeholders,
not shell variables or implicit lookup defaults. `discover` only reads selected
paths and file identities; it does not start a process or establish receiver
permissions. Multiple non-equivalent SDK candidates return `INCOMPLETE`.

```text
python -I -B qt_environment.py discover --python /host/qt-venv/bin/python --cmake /host/cmake --ctest /host/ctest --qt-sdk /host/qt-sdk --otool /host/otool --read-root /host/compiler-sdk --output /project/qt-discovered.json
python -I -B qt_environment.py observe --profile /project/qt-discovered.json --report-dir /evidence/observe-1 --output-profile /project/qt-observed.json --adapt-loader-paths
python -I -B qt_environment.py probe --profile /project/qt-observed.json --work-dir /scratch/qt-probe-1 --report-dir /evidence/probe-1 --receiver actual-host-scope-identity
```

`--compiler` optionally pins the selected C++ compiler in CMake; otherwise the
project/CMake compiler selection applies and must be verified in its actual scope.
`--otool` and `--adapt-loader-paths` are optional macOS adaptation inputs. The
adapter queries the declared CMake/CTest versions and, when present, qmake's
query output. It retains complete raw version strings, including vendor text.
A distribution's qmake prefix may differ from the selected versioned SDK: that
fact is retained, while configure explicitly selects the bound SDK metadata.
The actual probe decides whether the combination works; a query is not proof of
native execution. No query result triggers an installation or permission change.

When `otool` is selected, observation follows the chosen QtCore library's
non-system dependency closure with recorded `otool -L` calls. It records those
files' identities and actual library/framework directories rather than scanning
the whole SDK or package manager. `@loader_path` is resolved from its owner;
`@rpath` requires explicitly supplied `--dependency-directory` candidates.
Unresolved or ambiguous dependencies remain diagnostics. System shared-cache
libraries are not assumed to exist as loose files. Other operating-system
loaders need their appropriate observation adapter; this package does not label
unobserved dependencies as verified.

`--adapt-loader-paths` creates a **new** profile with discovered canonical
`DYLD_FRAMEWORK_PATH` / `DYLD_LIBRARY_PATH` prefixes for the known macOS layout.
It preserves the selected environment; an existing conflicting explicit `set`
is diagnosed rather than silently replaced. These paths and `read_paths` are
material for the original host's scope/Readback, not a permission grant. Include
CMake's runtime resources, compiler/SDK dependencies and the declared interpreter
in that scope as required by the actual tools. Observation is normally a host
preparation command; run the real probe in each receiver's actual declared
permissions before depending on its result.

The explicit public smoke flow runs configure, build, CTest and a QtCore CLI
once each, recording each command separately. Each finite child command has a
900-second timeout by default, while an enclosing host can impose its own
stricter whole-command budget. It creates only caller-selected fresh work and
report directories, never an old build cache. The fixture imports QtCore and
checks three Unicode scalar values plus its CTest record. This establishes only
this small environment operation, not the target project's business acceptance.

A failed stage is returned once; later stages are not executed. Correct the
configuration or fixture in authorized scope, use a new report path, and retain
the old evidence. When all commands were captured and only result retrieval was
interrupted, use the read-only path:

```text
python -I -B qt_environment.py inspect --profile /project/qt-observed.json --report-dir /evidence/probe-1 --receiver actual-host-scope-identity
```

`inspect` loads captured command records, stdout and JUnit. It never overwrites
`probe.json`, recreates a process or accepts missing/incomplete operations. The
host may save its returned assessment separately. `stack_runtime.reuse_probe`
compares the profile, declared file observations and actual receiver identity;
when the selected dependency closure has not been observed, actual probe PASS
remains valid for that run but reusable dependency evidence remains UNKNOWN;
changed related libraries require affected verification, while a new unrelated
business input does not cause the package to repeat all environment queries.
Receiver identity and permissions are supplied by the host, not authenticated by
this public helper.

## Project commands and configuration precedence

```text
python -I -B qt_cmake.py configure --profile /project/qt-observed.json --source /isolated/source --build-dir /isolated/build --report-dir /evidence/configure-1 --config Debug --define PROJECT_LABEL=custom
python -I -B qt_cmake.py build --profile /project/qt-observed.json --build-dir /isolated/build --report-dir /evidence/build-1 --config Debug --target project-target
python -I -B qt_cmake.py test --profile /project/qt-observed.json --build-dir /isolated/build --report-dir /evidence/test-1 --config Debug
```

Each bridge call runs one subprocess. `--timeout` can specify the host-approved
finite command timeout. An optional explicit `--cmake` or `--ctest` must match
the profile's invocation binding; it never silently selects a different tool.

Configure supports `--preset`, `--generator` and repeated `--define` values.
Profile environment changes apply to its child only, leaving the parent and
other stacks unchanged. Native CMake Preset semantics still apply inside CMake;
configure-preset-only environment values are not silently inherited by later
build/test invocations. Place values needed by all phases in the shared profile.
The adapter supplies explicit `Qt6_DIR`, `Qt6Core_DIR` and available
`Qt6CoreTools_DIR`, which take command-line precedence over stale preset/cache
locations. A conflicting explicit project Qt definition is diagnosed. Other
project definitions and existing caches remain governed by the project and
CMake; the adapter does not erase them or rewrite `CMakePresets.json`.

A profile's `environment.set` takes precedence over the parent for selected
keys; `environment.prepend` prepends ordered directories and retains the parent
suffix. It cannot declare both operations for one key. Only nonsecret explicit
configuration is recorded. Native Preset state/output must be examined when a
project intentionally adds its own environment changes.

## Independent checking and report recovery

The existing protected verifier copies `check_ctest.py`, plus the same public
`qt_environment.py`, `stack_runtime.py` and `native_dependencies.py` bytes. These public dependencies
are explicitly `shared` entries. The selected project profile must also be
bound as a shared verifier input; the project expectation and assertion sources
remain private. The checker verifies these paths are inside the actual
`FOUNDRY_VERIFIER_ROOT` **before importing** its dependencies. It imports only
its own siblings, including under isolated Python `-I` execution.

```text
python -I -B /protected/check_ctest.py --profile /protected/qt-profile.json --build-dir /isolated/build --report-dir /report-staging/ctest --expected /protected/expected.json --foundry-check-id ctest-contract
```

The expectation remains the project's independently maintained nonempty
`{"required_tests":["project-test"]}` list. Its trusted test assertions must
also be preserved: a matching test name with unconditional success is not
business proof. CTest is invoked once; ordinary test failures retain ASSERTION,
while missing execution or malformed/incomplete evidence remains ERROR. The
public environment smoke fixture is not a replacement for these assertions.

For the existing resource protocol, declare these attachments (adjust the
`ctest` child name together with the command's fresh report directory):

```json
{
  "required_checks": ["ctest-contract"],
  "report_files": [
    "summary.json",
    "ctest/invocation.json",
    "ctest/stdout.txt",
    "ctest/stderr.txt",
    "ctest/junit.xml",
    "ctest/check-result.json"
  ],
  "result_protocol": "STRUCTURED_V1"
}
```

Use `resource://report-staging/ctest` in actual resource command argv. The host
resolves it and archives the declared attachments before successful cleanup.
After cleanup, read archived paths from `resource_reports`, not obsolete paths
inside invocation records. `inspect_report` in the protected checker evaluates
retained JUnit without executing CTest; `stack_runtime.read_capture` retrieves
complete retained commands. Missing reports do not authorize a replay. The
existing host retains attempt history and owns cleanup, recovery and repair.

## Delivery and future upgrades

Deliver the selected public files in one relative directory: `qt_cmake.py`,
`qt_environment.py`, `stack_runtime.py`, `native_dependencies.py`, `probe-CMakeLists.txt`,
`probe-main.cpp` and this guide. The project owns its local profile and should
re-run explicit discovery/observation when relevant installation conditions
change, rather than copying a developer's venv or private preparation directory.
Keep checker/expectation delivery separate. A target may use its existing
explicit host tools; the package does not require installing duplicates.

Select version 2 explicitly and preserve version 1 evidence. Use the existing
complete-selection upgrade/material flow and C/G/N merge for project custom
files; do not overwrite old bindings, profiles, budgets or accepted evidence.
Fresh materials are not runtime authorization. This package does not alter the
fixed WP10 package, continuation Readback, old attempts, protocol 2.9 or G1/G2.

The initial implemented observation is macOS QtCore with CMake/CTest. GUI/QML,
plugins, deployment, cross-compilation, alternate SDK layouts and other systems
are not implied by a passing native QtCore probe. They can use explicit project
bindings and their own scoped verification without a new global prohibition.
