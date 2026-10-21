# Target-owned record adapter

`target.py` is an optional read-only adapter delivered with this complete public
package. It reads explicitly selected DATA, DOC and host-review records without
Foundry, its database, preparation helpers, private expectations or a model.
The existing sidebar and PiP use the same Observer, cache and front-end state.
It never calls a business tool, checker, report recovery or repair endpoint.

## Delivery and startup

Select the package with the existing prepare/consume entry. The host validates
`consume.prepare_call(materials, "target-dashboard", args)` before its normal
handoff. Deliver the complete selected package; keep project mapping, labels,
inputs, results and evidence outside the package. Copy only that public
selection's `name`, `version`, and each file's `path`/`sha256` into the following
`component` object. Do not give the target private checker materials.json.
The observer validates that public binding at startup; this does not authorize
business execution or require a new install/approval process.

```sh
/selected/.venv/bin/python -I -B /delivered/local-dashboard/1/target.py --config /project/observer.json
```

```json
{
  "component": {
    "name": "local-dashboard", "version": "1",
    "files": [{"path": "capability.json", "sha256": "replace-with-selected-hash"}]
  },
  "runs": [{
    "id": "data-current",
    "selection": {"kind": "harness_run", "project_id": "sales",
      "project_version": "v1", "run_id": "task-002"},
    "record": "runs/task-002/display.json"
  }]
}
```

The abbreviated `files` example must be replaced by the **complete selected
public package list**, including the descriptor, tools, guides and web assets.
`record` is relative to observer.json. Each run explicitly selects its own
record, with matching project/version/run identity; no directory scan, latest
report fallback or Foundry prepared ID is required. Missing reports do not
prove that execution never occurred. A referenced historical report remains
historical; its display cannot prove this run newly executed a tool.

The chosen interpreter is the target's declared host dependency; the launcher
does not find, install or replace Python. Host prepare/consume checks its bound
invocation path. Direct CLI users must use the declared `.venv` themselves.

## Target mapping and native records

This ordinary display configuration explains the target's existing files; it
is not a second acceptance, budget or execution ledger. If the target already
has a suitable reader, it can keep using Observer directly instead.

```json
{
  "selection": {"kind": "harness_run", "project_id": "sales",
    "project_version": "v1", "run_id": "task-002"},
  "title": "第二批销售汇总", "scope_ref": "本批数据与声明检查",
  "scope_complete": true,
  "items": [{
    "item_id": "summary", "label": "销售汇总", "format": "data-summary",
    "report": "reports/check-002.json", "check_ids": ["data-summary"],
    "evidence_ref": "task-002/check-002",
    "files": {
      "input": {"path": "input.csv"}, "config": {"path": "project.json"},
      "actual": {"path": "actual.json"},
      "expected": {"sha256": "replace-with-independent-expectation-hash"}
    }
  }],
  "steps": [
    {"step_id": "summary-output", "label": "计算成果", "item_id": "summary", "phase": "output"},
    {"step_id": "summary-check", "label": "独立核对", "item_id": "summary", "phase": "check",
     "depends_on": ["summary-output"]}
  ]
}
```

All native paths are relative to this display.json, or explicit absolute host
paths. Use display-safe titles/labels/evidence IDs; raw diagnostics, paths,
outputs, environment values and credentials are not sent to the page. Source
revision is a digest of the files actually read, not an invented business event.
Source files should be replaced atomically by their existing owner. The reader
does not write them. A mixed/incomplete update shows a gap or stale binding;
the next observation recovers from those files without replay. A report gap is
isolated to its declared item, so other complete items and steps remain visible.
Within the same selected scope and item mapping, the reader retains that item's
last FAIL/ERROR/INVALIDATED with an explicit gap; a prior PASS becomes UNKNOWN.
Changing the scope or mapped inputs does not inherit this temporary memory.
Whole-record identity or mapping errors still use the existing scope-level gap.

| Format | Required report and declared files |
|---|---|
| `data-summary` | Native checker `observation_binding.files`: input/config/actual/expected. Current input/config/actual are paths; expected may be its previously fixed private hash. |
| `doc-export` | Existing input_bindings for tool/config/notes/sources plus expected_sha256; configure those five keys. PASS also requires actual_export/actual_sha256 and the actual successful CLI execution record. The checker-owned temporary export may already be cleaned; the report is the preserved export evidence. |
| `host-review` | Native checker observation_binding: task/workflow/snapshot/expectation, input:key, output:name, and snapshot:relative-path for each consumed copy/evidence. Map exactly these keys to the corresponding target/archive files. Only expectation may use its fixed hash. |

For host-review, semantic keys come from the existing task/snapshot mapping,
not from recursively scanning the project. Task/workflow/input/output paths
refer to the current selected task; snapshot keys refer to its retained fixed
snapshot. The configured file-key set must equal the report's observed set.
Provide the project-required check IDs (host-review uses `host-review`; DOC
uses `document-export`). The adapter does not authenticate reviewers or decide
the truth of screenshots/search claims. Synthetic supplied observations remain
engineering fixtures even when their byte checks pass.

DATA and host-review checks now add these optional observation hashes while
reading their normal inputs. Existing check results/classifications remain
unchanged. Old reports remain usable under their original contract; without
enough binding facts this optional view says “待核实”, rather than rewriting
old evidence or running a checker to fill the gap. No all-project migration is
required. DOC uses its existing report fields unchanged.

The mapping shows `PASS` as **检查通过**, never as whole-Harness acceptance.
Only `scope_complete: true` and a nonempty declared item list yield a count of
passed declared checks; otherwise completion is unknown. One item stays one
item across repairs. Steps are separate from this denominator. File presence
alone is not a completed step; without process records the adapter does not
invent a running/finished tool. Failures/errors remain source facts, changed
file bindings invalidate this display, and missing/incomplete records stay
unknown. A null or absent binding means the checker did not observe those bytes,
not that the file changed. A declared check's explicit FAIL/ERROR remains visible
alongside its binding gap, including DOC input-path failures before export.
Only a recorded digest differing from currently readable bytes proves a version
change. PASS still requires the complete matching bindings and original format
checks. The original checker/target still owns any repair or acceptance.

Optional `budget` contains the original record's attempts_consumed/remaining,
copied by that record's owner without recomputation. Omit it when the target
has no budget record. Never fabricate Foundry attempts or add cumulative values.

## Lifecycle, upgrade and boundaries

CLI port/poll/idle flags, URL, SIGTERM/Ctrl-C/stop(), reconnect and shared PiP
behavior follow [the public guide](guide.md). Closing/restarting the observer
affects only its own service. Another run or the business process continues;
reopening reads its explicit current files and does not run the target again.

Use the existing C/G/N merge/apply path for target-owned delivered files.
Keep customized mapping/labels outside public package files, preserve conflicts
for the normal resolver, and update the public component binding only for the
selected new package. Restart the observer to use that version; keep old
package/run/evidence and do not restart the business. Removing the optional
observer does not remove business files, shared dependencies or evidence.

WP08 engineering tests and browser observations cover this adapter, native
small-file CLI records and shared layouts. They do not establish a new real
Harness/model task, PRD semantic/visual acceptance, another device, every
browser/PiP case, user comprehension, or performance benefit. H01–H09 retain
their original full acceptance requirements; protocol 2.9 remains unchanged.

项级历史只在共享投影校验成功后更新；来源暂不可读而保留旧失败时，同时保留该失败原有的证据引用，不把它绑定到尚未读出的新报告。
