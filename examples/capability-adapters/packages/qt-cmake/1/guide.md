# Qt / CMake adapter, version 1

Select this package for a project that already has a CMake build and CTest tests,
including Qt projects. It provides a reusable invocation interface, not project
test answers or a build controller. Select explicit host Python, CMake, CTest and
Qt SDK bindings; supply versions observed by the host. CTest 3.21 or newer is
needed for its JUnit output. No tool or SDK is installed by this package.

Use a project-owned isolated source copy where project configuration can write,
an isolated build directory, and a new report directory for each invocation.
Keep the original project and shared SDK read-only through the existing runtime
scope. `-S`/`-B` direct normal CMake output but do not sandbox project CMake code.
No global build-directory exclusion or framework symlink scanning is added.

The tool accepts three separate operations; placeholders below are supplied by
the selected environment and project, not searched from PATH:

```text
python -I -B qt_cmake.py configure --cmake /resolved/cmake --source /isolated/source --build-dir /isolated/build --report-dir /isolated/evidence/configure-1 --config Debug --define CMAKE_PREFIX_PATH=/resolved/qt-sdk
python -I -B qt_cmake.py build --cmake /resolved/cmake --build-dir /isolated/build --report-dir /isolated/evidence/build-1 --config Debug --target project-target
python -I -B qt_cmake.py test --ctest /resolved/ctest --build-dir /isolated/build --report-dir /isolated/evidence/test-1 --config Debug
```

`configure` also supports `--generator` and repeated `--define NAME[:TYPE]=VALUE`;
`build` supports repeated `--target`; tests may select a project-declared subset
with `--test-regex`. Each call launches at most one CMake or CTest process, with
no shell, retry, implicit configuration/build or network/credential setup. CMake
or project code can itself launch its normal build/test children. The existing
host controls resource permissions, command timeout, process cleanup and budget.
The package has no attempt counter or authority store. A command that fails is
recorded and returned once; the caller decides a later authorized repair.

Each report directory contains `invocation.json`, `stdout.log`, `stderr.log`
and, for tests, CTest's `junit.xml`. Existing report directories are left intact
and not replayed or overwritten. An interrupted STARTED record is unresolved,
not success. Reading retained records does not rerun a command. Configuration
and build return codes are process results, not product acceptance.

The independent checker is a `verification_files` entry. Copy it using the
existing protected-verifier flow, keep the project's own nonempty expectation
JSON (`{"required_tests":["project-specific-test"]}`) in that protected root,
and call the protected copy with explicit project parameters:

```text
python -I -B /protected/check_ctest.py --ctest /resolved/ctest --build-dir /isolated/build --report-dir /isolated/evidence/independent-check-1 --expected /protected/project-expected.json --config Debug
```

The checker performs one fresh CTest invocation and evaluates its actual JUnit
against the independent required names. It does not trust the producer's
reported success. The plan may use this as its test step instead of first
running the ordinary `test` operation; if both are chosen, they are two explicit
invocations, never hidden retries. Bind the isolated build to the current
checked source/product through the existing plan, artifacts and protected
resource flow; parsing a producer-writable historical XML alone is not proof of
that binding or of fresh execution. For retained diagnostics, import the
protected copy and call `inspect_report(junit_path, invocation_record,
required_tests)` after loading the same independent expectation with
`read_expected`. This only reads evidence; it does not repair missing command
completion or grant acceptance. Empty/invalid required-test lists are ERROR on
both the execution and read-only paths.

Required test names establish coverage, not the correctness of the test bodies.
The project must supply its independently trusted assertions through its existing
contract: for example, preserved test sources or protected external tests. A
same-named test replaced with unconditional success is not independent business
evidence. This adapter does not invent those project assertions.

For the existing resource contract, add `--foundry-check-id ctest-contract` and
set `--report-dir resource://report-staging/ctest` in the protected checker's
argv. Merge this fragment into the project's existing resource profile:

```json
{
  "required_checks": ["ctest-contract"],
  "report_files": [
    "summary.json",
    "ctest/invocation.json",
    "ctest/junit.xml",
    "ctest/stdout.log",
    "ctest/stderr.log",
    "ctest/check-result.json"
  ],
  "result_protocol": "STRUCTURED_V1"
}
```

The existing host resolves `resource://` before dispatch; argv does not expand
shell environment variables. `ctest` is an example child name; another new
child is usable when the declared attachment paths match it. The checker creates
the new child of this command's report-staging directory and writes
`FOUNDRY_REPORT_DIR/summary.json`
with the actual injected Case/command IDs. The host archives all six declared
files before successful cleanup removes scratch and report-staging. Missing
declared attachments follow the existing incomplete-report handling, retaining
resources without replaying CTest. `build/Testing` also needs the existing
runtime's approved writable build copy.

After cleanup, use the saved `resource_reports[].path` entries (under the host's
`observation_root/reports`) for `ctest/junit.xml` and `ctest/invocation.json`.
Pass the archived JUnit path, parsed invocation JSON and required tests loaded
from the same protected expectation to `inspect_report`.
Paths inside the original invocation record are historical provenance, not
locations to reopen after cleanup; keep that record unchanged. Recovery uses
the existing command observation, without allocating resources or running the
checker again. Read-only inspection remains diagnostic, not a new acceptance.

The expectation and checker are separate protected `checker_files`, never
producer materials. When `FOUNDRY_VERIFIER_ROOT` is supplied, both the executing
checker file and expectation must resolve inside that protected copy before
CTest can start. `network.mode: NONE` is sufficient for an offline Qt test;
project-specific service/effect accounting needs its existing dedicated checker,
not a claim that this adapter verified those resources. The profile's one check
covers every test required by the protected project expectation, not a fixed
list of package sample tests. Without this flag the exit-code/diagnostic
interface remains usable for non-resource checks; its plain `check-result.json`
is not a resource summary.

Missing required tests and reported test failures are ASSERTION; missing or
malformed reports, no tests, skipped/not-run tests and tool/process failures
are ERROR. Neither passes. Extra tests are allowed but must also
complete successfully. Exit codes are 0 / 1 / 2 for PASS / ASSERTION / ERROR;
stdout and `check-result.json` are diagnostics, and the optional bound summary
uses the existing verification contract, never a new controller acceptance record. Unit fixtures
and an isolated native engineering run do not establish a delivered Harness's
new-task, upgrade, second-device or business acceptance.
