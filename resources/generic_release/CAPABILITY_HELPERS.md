# Optional capability preparation and observation

This directory provides the host-side preparation helpers. It does not install
capabilities, start a Harness build, grant execution authority, or run checks.
Projects without capability packages keep using the original
[reviewed build route](../../docs/GENERIC_BUILD_CLI.md).

## Select an extracted capability

Obtain the explicitly selected capability candidate separately and extract each
version into its own new directory. Keep previous packages and project evidence.
The candidate's `CAPABILITY_PACKAGE_MANIFEST.json` records its name, version,
declared files and environment requirements; it does not prove runtime support.
The source candidate includes declared checker code for the host. Do not give
the whole source candidate or host materials file to a producer. The existing
preparer separates public sources/tools from protected verification files.

Use the receiving machine's Python 3.11+ environment. For example, save this as
an ordinary configuration outside the package, replacing each placeholder:

```json
{
  "project_root": "/project",
  "selections": [{"directory": "/selected/data-summary-v1", "version": "1"}],
  "environment_bindings": {
    "python": {"path": "/project/.venv/bin/python", "observed_version": "3.11.9"}
  }
}
```

`observed_version` must be the receiving host's actual observation, not the
example value. Bind CMake, CTest and the Qt SDK locally when selecting qt-cmake.
Do not copy a developer virtual environment or infer SDK availability from a ZIP.

```sh
/project/.venv/bin/python -I -B prepare.py --config /host/config.json --output /host/new-materials
/project/.venv/bin/python -I -B consume.py --materials /host/new-materials/materials.json --tool summarize-csv -- --help
```

[prepare.py](prepare.py) creates new host materials; [environment.py](environment.py)
resolves explicitly supplied bindings without probing or installation.
[consume.py](consume.py) checks the selected source/version and returns an argv;
it does **not** execute that argv. The original authorized host executes it and
retains its normal budget, checking, cleanup and report recovery responsibilities.
Project expectations and input/output paths remain project-owned.

## Change the selection and preserve customization

[upgrade.py](upgrade.py) takes `--previous`, a complete next `--config`, and a new
`--output`. It prepares differences and replacement materials without applying
files, resetting authority or replaying work. Keep the previous selection and
reports. Target-file changes continue through the existing
[merge](../harness-composition-upgrade/helpers/merge.py) and
[apply](../harness-composition-upgrade/helpers/apply.py) helpers, using the actual
generated baseline and project-owned current files; do not overwrite customizations
by copying an entire new package onto a target.

## Optional dashboards

Select `local-dashboard` independently when needed. [foundry_dashboard.py](foundry_dashboard.py)
uses this archive's Foundry reader and an explicit Program/prepared configuration.
Its `--config` contains `materials` and `runs`, each with `id`, `control_db` and
`selection` (`kind: foundry_build`, `project_id`, `project_version`, `run_id`,
`program_id`, `prepared_event_id`). It never discovers the latest run or advances it.

The capability's own `target.py` and `target-guide.md` describe target-owned
records; that delivered observer does not require Foundry. Both views share the
selected observer's state. Starting or stopping it affects only observation.
The package guides describe actual tool inputs and the remaining acceptance
boundaries. Candidate preparation and relocated engineering checks do not prove
real new-task, second-device, browser, model or whole-Harness acceptance.

`local-dashboard@3` optionally adds cumulative work, individual implementation/check
steps and their history. For Foundry, a work unit is an original Workpack in the
selected prepared scope's displayed plan, plus each Workpack affected by a distinct
confirmed extra-defect repair root. Retries and continuations of that repair do
not add units. Current valid acceptance remains separate: historical completion
does not restore invalidated acceptance, and stage/history counts do not enlarge
the acceptance denominator. There is no cross-prepared aggregation or change to
scheduling or budgets.

The default raw Foundry reader interface stays unchanged; the host opts in only
when the selected component supports the new fields. Target-owned sources without
those fields retain their previous display. Versions 1 and 2, existing installations
and fixed older archives do not switch automatically. Select version 3 through
the existing prepare/consume and upgrade flow with its complete new file binding.
This source update does not deploy to the original device, push or publish a
release, replace a fixed older archive, or change R3. Engineering and browser
evidence remain separate from actual target acceptance.

## Optional stack environment profiles

See [STACK_ENVIRONMENT.md](STACK_ENVIRONMENT.md) for format 1, full Qt/Python
preparation examples and the [author template](author-template/README.md).
Select qt-cmake@2 or python-environment@1 separately.
`selection.environment_profile` binds public configuration to the selected
package version; prepare checks files but runs no probes.
[stack_handoff.py](stack_handoff.py) returns a profile-bound argv or writes a
new public-only delivery. It does not execute or authorize it.
[stack_runtime.py](stack_runtime.py) provides explicit child capture and read-only
retrieval; native dependencies are observed only when selected.
Keep private checks separate and rebind local tools in the delivered directory.
The current environment acceptance is local clean execution plus selected
environment variations, not a mandatory second-device test.


`local-dashboard@4` additionally returns `view_urls.embedded` and
`view_urls.browser` in its startup response. The Chat host opens the selected URL
in the Codex browser panel or external Chrome using available host tools. No
browser launch is performed by the observer. Embedded presentation hides PiP and
fullscreen; external/unspecified presentation detects each API independently.
Version 4 is an explicitly selected capability package, not an implicit upgrade
of older deployments or a new generic-runtime requirement. Counts, current
acceptance, source isolation and business budgets are unchanged.
